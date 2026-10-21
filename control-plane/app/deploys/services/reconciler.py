"""Reconciler: keeps the running deploys' replicas alive.

Every few seconds (and at once when a heartbeat asks) it looks at the replica rows of the
running deploys, which heartbeats keep current, and:

- marks the replicas of a dead node `lost`;
- turns a replica that has failed its probe for too long into a death;
- fetches the log tail of a death while the container still exists;
- replaces a dead replica after its backoff: the same slot (replica id), the same node when
  it is ready, else another one;
- removes containers that no live deploy wants (GC);
- re-renders the routes when the set of serving replicas changed.

The agents only report; this is the one place that decides to restart. One instance runs in
the process. Replacements run as tasks so a slow image pull does not hold the loop.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import grpc

from app.agents.client import Agents, UnknownNodeError
from app.apps.services.facade import AppNotFoundError, AppsFacade
from app.deploys.repositories.deploys import Deploy
from app.deploys.repositories.replicas import DEAD_STATES, Replica
from app.deploys.services.health import (
    UNHEALTHY_REPLACE_AFTER,
    HealthState,
    death_changes,
    lost_changes,
    tail_text,
)
from app.deploys.services.runner import (
    remove_replica_quietly,
    replica_env,
    start_replica,
)
from app.deploys.services.scheduler import NoRunnersError, pick_node
from app.deploys.uow import DeploysUoW
from app.nodes.services.facade import NodesFacade

logger = logging.getLogger(__name__)

PLACEMENT_RETRY_SECONDS = 15.0  # after a replacement that could not be started
LOG_FETCH_LINES = 40  # read a few more than are kept: the last lines may be blank


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Reconciler:
    def __init__(
        self,
        state: HealthState,
        uow_factory: Callable[[], DeploysUoW],
        agents: Agents,
        nodes: NodesFacade,
        apps: AppsFacade,
        reapply_routes: Callable[[str], Awaitable[int | None]],
        trusted_proxy: str,
        *,
        interval: float = 5.0,
        initial_delay: float = 0.0,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._state = state
        self._uow_factory = uow_factory
        self._agents = agents
        self._nodes = nodes
        self._apps = apps
        self._reapply_routes = reapply_routes
        self._trusted_proxy = trusted_proxy
        self._interval = interval
        self._initial_delay = initial_delay
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._replacing: dict[str, asyncio.Task[None]] = {}  # replica id -> its replacement

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="replica-reconciler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        tasks = list(self._replacing.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def join(self) -> None:
        """Wait for the replacements in flight (tests)."""
        while self._replacing:
            await asyncio.gather(*self._replacing.values(), return_exceptions=True)

    async def _run(self) -> None:
        # Right after a start the nodes' last_seen_at is old: give the agents time to report,
        # or every node would look dead.
        await asyncio.sleep(self._initial_delay)
        signal = self._state.signal
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("reconciler: tick failed")
            try:
                await asyncio.wait_for(signal.wake.wait(), self._interval)
            except TimeoutError:
                pass
            signal.wake.clear()

    async def tick(self) -> None:
        """One pass. Never starts a replacement for a slot that already has one in flight."""
        now = self._clock()
        await self._collect_garbage()

        runners = await self._nodes.runners()
        ready = {r.name for r in runners if r.ready}
        dead = {r.name for r in runners if r.dead}

        async with self._uow_factory() as uow:
            deploys = [d for d in await uow.deploys.list_all() if d.status == "running"]
            rows = await uow.replicas.list_running(d.id for d in deploys)
        by_deploy: dict[str, list[Replica]] = {}
        for row in rows:
            by_deploy.setdefault(row.deploy_id, []).append(row)

        routes_changed = False
        for deploy in deploys:
            for row in by_deploy.get(deploy.id, []):
                changes = self._judge(row, now, ready, dead)
                if changes:
                    if await self._write(row, changes):
                        routes_changed |= row.serving != replace(row, **changes).serving
                        row = replace(row, **changes)
                    else:
                        continue
                await self._handle_dead(deploy, row, now, ready, by_deploy[deploy.id])

        if routes_changed:
            self._state.signal.routes_dirty = True
        await self._reapply_if_dirty()

    def _judge(
        self, row: Replica, now: datetime, ready: set[str], dead: set[str]
    ) -> dict[str, Any]:
        """A running row that has to be written off: its node is dead, or it hangs."""
        if row.state != "running":
            return {}
        if row.node in dead:
            logger.warning("replica %s: node %s is dead", row.id, row.node)
            return lost_changes()
        if (
            not row.healthy
            and row.unhealthy_since is not None
            and now - row.unhealthy_since >= UNHEALTHY_REPLACE_AFTER
            and row.node in ready
        ):
            logger.warning("replica %s on %s: health check failed, replacing", row.id, row.node)
            return death_changes(row, now, "exited", None, "health check failed")
        return {}

    async def _write(self, row: Replica, changes: dict[str, Any]) -> bool:
        async with self._uow_factory() as uow:
            updated = await uow.replicas.update(row.id, node=row.node, **changes)
            if updated is not None:
                await uow.commit()
        return updated is not None

    async def _handle_dead(
        self,
        deploy: Deploy,
        row: Replica,
        now: datetime,
        ready: set[str],
        siblings: list[Replica],
    ) -> None:
        if row.state not in DEAD_STATES:
            return
        if row.tail_pending:
            row = await self._capture_tail(row, ready)
        if row.index >= deploy.desired_replicas or row.id in self._replacing:
            return
        if row.retry_at is not None and row.retry_at > now:
            return
        task = asyncio.create_task(
            self._replace(deploy, row, siblings, ready), name=f"replace-{row.id}"
        )
        self._replacing[row.id] = task
        task.add_done_callback(lambda _: self._replacing.pop(row.id, None))

    async def _capture_tail(self, row: Replica, ready: set[str]) -> Replica:
        """The app's last output, while the dead container still exists; best effort."""
        tail = row.log_tail
        if row.node in ready:
            try:
                text = await self._agents.logs(
                    node=row.node, replica_id=row.id, tail_lines=LOG_FETCH_LINES
                )
                tail = tail_text(text)
            except (grpc.aio.AioRpcError, UnknownNodeError) as e:
                logger.info("replica %s: no log tail: %r", row.id, e)
        changes = {"log_tail": tail, "tail_pending": False}
        if await self._write(row, changes):
            return replace(row, **changes)
        return row

    async def _replace(
        self, deploy: Deploy, row: Replica, siblings: list[Replica], ready: set[str]
    ) -> None:
        """Start a new container for the slot; the row follows it."""
        try:
            app = await self._apps.get_app_unchecked(deploy.app_name)
        except AppNotFoundError:
            return
        now = self._clock()

        # The same node first: its image is there and nothing else moves. Its old container
        # must be gone first (same name), so a node that cannot remove it is skipped.
        removed = await remove_replica_quietly(self._agents, row.node, row.id)
        same_node = removed and row.node in ready

        candidates = [n for n in ready if same_node or n != row.node]
        counts = Counter(r.node for r in siblings if r.id != row.id and r.state == "running")
        try:
            if same_node:
                node = row.node
            else:
                async with self._uow_factory() as uow:
                    total = await uow.replicas.count_running_by_node()
                node = pick_node(candidates, counts, total)
            result = await start_replica(
                self._agents, node, deploy, row.index, replica_env(app, self._trusted_proxy)
            )
        except (NoRunnersError, grpc.aio.AioRpcError, UnknownNodeError) as e:
            logger.warning("replica %s: replacement failed: %r", row.id, e)
            await self._retry_later(row, now)
            return

        async with self._uow_factory() as uow:
            moved = await uow.replicas.rehome(row.id, result.node, result.host_port, now)
            if moved:
                await uow.commit()
        if not moved:  # retired or replaced meanwhile: do not leave the container behind
            _ = await remove_replica_quietly(self._agents, result.node, row.id)
            return
        logger.info("replica %s replaced on %s", row.id, result.node)
        self._state.signal.routes_changed()

    async def _retry_later(self, row: Replica, now: datetime) -> None:
        _ = await self._write(
            row, {"retry_at": now + timedelta(seconds=PLACEMENT_RETRY_SECONDS)}
        )

    async def _collect_garbage(self) -> None:
        garbage, self._state.signal.garbage = self._state.signal.garbage, set()
        for node, replica_id in garbage:
            if await remove_replica_quietly(self._agents, node, replica_id):
                logger.warning("replica %s on %s: not wanted, removed", replica_id, node)
                self._state.stale_since.pop((node, replica_id), None)

    async def _reapply_if_dirty(self) -> None:
        signal = self._state.signal
        if not signal.routes_dirty:
            return
        signal.routes_dirty = False
        if await self._reapply_routes("replica health") is None:
            signal.routes_dirty = True  # look again next round
