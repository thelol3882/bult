"""Replica storage behind a Protocol.

A replica row says where a deploy's container runs. Rows stay after a replica is retired
(`removed`), so the history of a deploy keeps showing where it ran.
"""

from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

ReplicaStatus = Literal["running", "removed"]
# What the platform knows about the container: `exited`/`oom` come from the node,
# `lost` is set when the node is dead, `crashloop` when replacing it did not help.
ReplicaState = Literal["running", "exited", "oom", "lost", "crashloop"]
DEAD_STATES: tuple[ReplicaState, ...] = ("exited", "oom", "lost")  # to be replaced


def replica_id(deploy_id: str, index: int) -> str:
    """The name of the replica on the node (and its row)."""
    return f"{deploy_id}-r{index}"


@dataclass
class Replica:
    """One container of a deploy; a replacement reuses the row (the slot)."""

    id: str
    deploy_id: str
    index: int
    node: str
    host_port: int
    status: ReplicaStatus = "running"
    created_at: datetime | None = None  # set by storage on add
    state: ReplicaState = "running"
    healthy: bool = True  # the node's health probe; meaningful while running
    exit_code: int | None = None  # of the last death
    reason: str = ""  # user-facing: why the last death happened
    log_tail: str = ""  # the app's last output at the last death
    tail_pending: bool = False  # a death whose log tail has not been fetched yet
    unhealthy_since: datetime | None = None
    failures: tuple[datetime, ...] = ()  # deaths in the crash-loop window
    retry_at: datetime | None = None  # the earliest time to replace it
    placed_at: datetime | None = None  # when the current container was started

    @property
    def serving(self) -> bool:
        """It may receive traffic."""
        return self.status == "running" and self.state == "running" and self.healthy


@dataclass(frozen=True)
class ReplicaView:
    """A replica as the API shows it."""

    index: int
    node: str
    host_port: int
    status: Literal["running", "unhealthy", "exited", "oom", "crashloop", "lost"]
    exit_code: int | None = None
    recent_failures: int = 0
    reason: str = ""
    log_tail: tuple[str, ...] = ()
    retry_at: datetime | None = None


# What `update` may change: the container's observed state, never its identity or place.
UPDATABLE_FIELDS = {f.name for f in fields(Replica)} - {
    "id",
    "deploy_id",
    "index",
    "node",
    "host_port",
    "status",
    "created_at",
}


class ReplicaRepository(Protocol):
    """Storage only; placement rules live in the scheduler and the runner."""

    async def save(self, replica: Replica) -> bool:
        """Insert or update by id as `running`; False if the deploy no longer exists."""
        ...

    async def list_running(self, deploy_ids: Iterable[str]) -> list[Replica]:
        """Running replicas of these deploys, ordered by (deploy, index)."""
        ...

    async def list_all_running(self) -> list[Replica]:
        """Every running replica, any deploy."""
        ...

    async def get_running(self, replica_ids: Iterable[str]) -> list[Replica]:
        """The running replicas with these ids; unknown and removed ids are left out."""
        ...

    async def list_on_node(self, node: str) -> list[Replica]:
        """Running rows placed on this node."""
        ...

    async def update(
        self, replica_id: str, *, node: str | None = None, **changes
    ) -> Replica | None:
        """Change the observed state of a running row; with `node`, only if the row is still
        placed there (a heartbeat must not write onto a row that moved). None if no row matches."""
        ...

    async def rehome(
        self, replica_id: str, node: str, host_port: int, now: datetime
    ) -> bool:
        """Point a dead row at its replacement container: running and healthy again, same
        failure history. False if the row is no longer a running dead one (it was retired or
        already replaced): the caller removes the container it just started."""
        ...

    async def reset_crashloops(self, deploy_id: str) -> int:
        """Give crash-looping rows of the deploy a fresh start: they are replaced at once."""
        ...

    async def mark_removed(self, replica_ids: Iterable[str]) -> None: ...

    async def count_running_by_node(self) -> dict[str, int]: ...


class InMemoryReplicaRepository:
    """Dict keyed by id; also the test fake."""

    def __init__(self) -> None:
        self._replicas: dict[str, Replica] = {}

    def forget_deploys(self, deploy_ids: Iterable[str]) -> None:
        """What ON DELETE CASCADE does."""
        gone = set(deploy_ids)
        self._replicas = {
            k: r for k, r in self._replicas.items() if r.deploy_id not in gone
        }

    async def save(self, replica: Replica) -> bool:
        previous = self._replicas.get(replica.id)
        created_at = previous.created_at if previous else datetime.now(UTC)
        fresh = replace(
            replica,
            status="running",
            created_at=created_at,
            placed_at=replica.placed_at or datetime.now(UTC),
        )
        if previous is not None:  # a replacement keeps the slot's history
            fresh = replace(
                fresh,
                state="running",
                healthy=True,
                unhealthy_since=None,
                retry_at=None,
                tail_pending=False,
                exit_code=previous.exit_code,
                reason=previous.reason,
                log_tail=previous.log_tail,
                failures=previous.failures,
            )
        self._replicas[replica.id] = fresh
        return True

    async def list_running(self, deploy_ids: Iterable[str]) -> list[Replica]:
        wanted = set(deploy_ids)
        found = [
            r
            for r in self._replicas.values()
            if r.deploy_id in wanted and r.status == "running"
        ]
        return [replace(r) for r in sorted(found, key=lambda r: (r.deploy_id, r.index))]

    async def list_all_running(self) -> list[Replica]:
        running = [r for r in self._replicas.values() if r.status == "running"]
        return [replace(r) for r in sorted(running, key=lambda r: (r.deploy_id, r.index))]

    async def get_running(self, replica_ids: Iterable[str]) -> list[Replica]:
        found = [self._replicas.get(rid) for rid in replica_ids]
        return [replace(r) for r in found if r is not None and r.status == "running"]

    async def list_on_node(self, node: str) -> list[Replica]:
        found = [
            r for r in self._replicas.values() if r.status == "running" and r.node == node
        ]
        return [replace(r) for r in sorted(found, key=lambda r: r.id)]

    async def update(
        self, replica_id: str, *, node: str | None = None, **changes
    ) -> Replica | None:
        unknown = changes.keys() - UPDATABLE_FIELDS
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        row = self._replicas.get(replica_id)
        if row is None or row.status != "running" or (node is not None and row.node != node):
            return None
        self._replicas[replica_id] = row = replace(row, **changes)
        return replace(row)

    async def rehome(
        self, replica_id: str, node: str, host_port: int, now: datetime
    ) -> bool:
        row = self._replicas.get(replica_id)
        if row is None or row.status != "running" or row.state not in DEAD_STATES:
            return False
        self._replicas[replica_id] = replace(
            row,
            node=node,
            host_port=host_port,
            state="running",
            healthy=True,
            unhealthy_since=None,
            retry_at=None,
            tail_pending=False,
            placed_at=now,
        )
        return True

    async def reset_crashloops(self, deploy_id: str) -> int:
        count = 0
        for rid, row in list(self._replicas.items()):
            if row.deploy_id == deploy_id and row.status == "running" and row.state == "crashloop":
                self._replicas[rid] = replace(
                    row, state="exited", failures=(), retry_at=None
                )
                count += 1
        return count

    async def mark_removed(self, replica_ids: Iterable[str]) -> None:
        for rid in replica_ids:
            if rid in self._replicas:
                self._replicas[rid] = replace(self._replicas[rid], status="removed")

    async def count_running_by_node(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._replicas.values():
            if r.status == "running":
                counts[r.node] = counts.get(r.node, 0) + 1
        return counts
