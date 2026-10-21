"""Replica health: what the nodes' heartbeats say about containers, and what a death costs.

The rules (deaths, backoff, crash loop, what a report changes) are plain functions over a
`Replica`; `ReplicaHealthService.record` applies them to a heartbeat. Replacing dead
replicas is the reconciler's job (reconciler.py).
"""

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.deploys.repositories.deploys import ACTIVE_STATUSES
from app.deploys.repositories.replicas import (
    DEAD_STATES,
    Replica,
    ReplicaView,
)
from app.deploys.uow import DeploysUoW

logger = logging.getLogger(__name__)

FAILURE_WINDOW = timedelta(minutes=10)
MAX_FAILURES = 5  # this many deaths inside the window: crash loop, stop replacing
BACKOFF_BASE = 10.0  # seconds before replacing after the first death; doubles each time
BACKOFF_MAX = 300.0
# A replica that keeps failing its probe is replaced after this long: slow starts and short
# stalls recover by themselves (the node needs 30 s of failures to call it unhealthy at all).
UNHEALTHY_REPLACE_AFTER = timedelta(seconds=60)
# A replica missing from a complete report is gone, unless it was started this recently
# (the node's list may predate the container).
MISSING_GRACE = timedelta(seconds=15)
# A container nobody wants is removed after being seen this long: placing a replica writes
# its row after the container starts.
STALE_GRACE = timedelta(seconds=15)
LOG_TAIL_LINES = 20
LOG_LINE_MAX = 500


@dataclass(frozen=True)
class Observation:
    """What a node says about one replica container."""

    replica_id: str
    state: Literal["running", "exited", "oom"]
    exit_code: int | None = None
    oom_killed: bool = False
    healthy: bool = True
    finished_at: datetime | None = None


def backoff(failures: int) -> timedelta:
    """Pause before replacing after the n-th death in the window: 10 s, 20 s, 40 s ... 5 min."""
    return timedelta(seconds=min(BACKOFF_BASE * 2 ** (max(failures, 1) - 1), BACKOFF_MAX))


def exit_reason(state: str, exit_code: int | None) -> str:
    if state == "oom":
        return "killed: out of memory"
    if exit_code is None:
        return "exited"
    return f"exited with code {exit_code}"


def death_changes(
    replica: Replica,
    now: datetime,
    state: Literal["exited", "oom"],
    exit_code: int | None,
    reason: str,
) -> dict[str, Any]:
    """The row after one more death: a backoff, or a crash loop after MAX_FAILURES in the window."""
    recent = tuple(t for t in replica.failures if now - t <= FAILURE_WINDOW)
    failures = (*recent, now)
    changes: dict[str, Any] = {
        "healthy": False,
        "exit_code": exit_code,
        "failures": failures,
        "unhealthy_since": None,
        "tail_pending": True,
    }
    if len(failures) >= MAX_FAILURES:
        return {
            **changes,
            "state": "crashloop",
            "reason": f"crash loop: {reason}",
            "retry_at": None,
        }
    return {
        **changes,
        "state": state,
        "reason": reason,
        "retry_at": now + backoff(len(failures)),
    }


def lost_changes() -> dict[str, Any]:
    """The node is dead: not the app's fault, so no failure is counted and no backoff applies."""
    return {
        "state": "lost",
        "healthy": False,
        "reason": "node is down",
        "log_tail": "",
        "tail_pending": False,
        "unhealthy_since": None,
        "retry_at": None,
    }


def observe(row: Replica, obs: Observation, now: datetime) -> dict[str, Any]:
    """What a node's report of the row's container changes (nothing: {})."""
    if row.state == "crashloop":
        return {}  # only a new deploy, a scale or a start gives it another chance

    if obs.state == "running":
        if row.state == "lost":  # the node came back with the container still running
            return {
                "state": "running",
                "healthy": obs.healthy,
                "unhealthy_since": None if obs.healthy else now,
                "retry_at": None,
            }
        if row.state != "running":
            return {}  # dying or hung and waiting to be replaced
        if obs.healthy == row.healthy:
            return {}
        return {"healthy": obs.healthy, "unhealthy_since": None if obs.healthy else now}

    if row.state != "running":
        return {}  # the death is recorded already
    if obs.finished_at is not None and row.placed_at is not None and obs.finished_at < row.placed_at:
        return {}  # the node still reports the previous container of this slot
    state = "oom" if obs.state == "oom" or obs.oom_killed else "exited"
    return death_changes(row, now, state, obs.exit_code, exit_reason(state, obs.exit_code))


def missing_changes(row: Replica, now: datetime) -> dict[str, Any]:
    """A complete report lacks a running row: the container is gone (removed behind our back)."""
    if row.state != "running":
        return {}
    placed = row.placed_at or row.created_at
    if placed is not None and now - placed < MISSING_GRACE:
        return {}
    return death_changes(row, now, "exited", None, "container is gone")


def view_status(row: Replica, node_ready: bool) -> Literal[
    "running", "unhealthy", "exited", "oom", "crashloop", "lost"
]:
    if row.state != "running":
        return row.state
    if not node_ready or not row.healthy:
        return "unhealthy"
    return "running"


def to_view(row: Replica, node_ready: bool, now: datetime) -> ReplicaView:
    status = view_status(row, node_ready)
    reason = row.reason
    if status == "unhealthy":
        reason = "health check failed" if not row.healthy else "node is not reporting"
    elif status == "running":
        reason = ""
    return ReplicaView(
        index=row.index,
        node=row.node,
        host_port=row.host_port,
        status=status,
        exit_code=row.exit_code,
        recent_failures=sum(now - t <= FAILURE_WINDOW for t in row.failures),
        reason=reason,
        log_tail=tuple(row.log_tail.splitlines()),
        retry_at=row.retry_at if status in ("exited", "oom") else None,
    )


def tail_text(text: str) -> str:
    """The last lines of an app's output, each cut short, for the user to see."""
    lines = [line[:LOG_LINE_MAX] for line in text.splitlines()[-LOG_TAIL_LINES:]]
    return "\n".join(lines)


class ReconcileSignal:
    """What heartbeats ask of the reconciler: re-render routes, remove stray containers."""

    def __init__(self) -> None:
        self.wake = asyncio.Event()
        self.routes_dirty = False
        self.garbage: set[tuple[str, str]] = set()  # (node, replica id)

    def routes_changed(self) -> None:
        self.routes_dirty = True
        self.wake.set()

    def collect(self, node: str, replica_id: str) -> None:
        self.garbage.add((node, replica_id))
        self.wake.set()


@dataclass
class HealthState:
    """Shared between heartbeat requests and the reconciler (one per process)."""

    signal: ReconcileSignal = field(default_factory=ReconcileSignal)
    stale_since: dict[tuple[str, str], datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthResult:
    routes_changed: bool
    garbage: tuple[str, ...]  # containers to remove from the node


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _deploy_of(replica_id: str) -> str | None:
    """The deploy id in "<deploy_id>-r<index>"; None for names we do not create."""
    deploy_id, sep, index = replica_id.rpartition("-r")
    return deploy_id if sep and deploy_id and index.isdigit() else None


class ReplicaHealthService:
    """The heartbeat side: record what a node reports, leave the reactions to the reconciler."""

    def __init__(
        self,
        uow_factory: Callable[[], DeploysUoW],
        state: HealthState,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._state = state
        self._clock = clock

    async def record(
        self, node: str, observations: Iterable[Observation], complete: bool
    ) -> HealthResult:
        """Apply one heartbeat. `complete`: the node listed every container it has, so a
        replica missing from the list is gone.

        Containers on the node that no live deploy wants (a deploy that is over, a replica
        that now runs on another node) are returned once they have been seen for STALE_GRACE.
        """
        now = self._clock()
        reported = {o.replica_id: o for o in observations}
        routes_changed = False
        unwanted: list[str] = []

        async with self._uow_factory() as uow:
            rows = await uow.replicas.list_on_node(node)
            known = {r.id for r in rows}
            changed: list[tuple[Replica, dict[str, Any]]] = []
            for row in rows:
                obs = reported.get(row.id)
                if obs is not None:
                    changes = observe(row, obs, now)
                elif complete:
                    changes = missing_changes(row, now)
                else:
                    changes = {}
                if changes:
                    changed.append((row, changes))

            for rid in reported.keys() - known:
                deploy_id = _deploy_of(rid)
                if deploy_id is None:
                    continue
                deploy = await uow.deploys.get(deploy_id)
                if deploy is None or deploy.status not in ACTIVE_STATUSES:
                    unwanted.append(rid)

            for row, changes in changed:
                if await uow.replicas.update(row.id, node=node, **changes) is None:
                    continue
                routes_changed |= row.serving != replace(row, **changes).serving
                if "failures" in changes and changes["state"] != row.state:
                    logger.warning(
                        "replica %s on %s: %s", row.id, node, changes["reason"]
                    )
            if changed:
                await uow.commit()

        return HealthResult(routes_changed, tuple(self._stale(node, unwanted, now)))

    def _stale(self, node: str, unwanted: list[str], now: datetime) -> list[str]:
        seen = self._state.stale_since
        for key in [k for k in seen if k[0] == node and k[1] not in unwanted]:
            del seen[key]
        ripe = []
        for rid in unwanted:
            since = seen.setdefault((node, rid), now)
            if now - since >= STALE_GRACE:
                ripe.append(rid)
        return ripe

    def forget(self, node: str, replica_id: str) -> None:
        self._state.stale_since.pop((node, replica_id), None)


__all__ = [
    "DEAD_STATES",
    "HealthResult",
    "HealthState",
    "Observation",
    "ReconcileSignal",
    "ReplicaHealthService",
]
