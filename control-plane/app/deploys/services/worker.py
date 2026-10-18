"""Deploy worker: claims queued/in-flight deploys under a lease and runs them.

The deploys table is the queue. A claim is a short transaction ("mine until now + lease");
a heartbeat renews it while the deploy is processed; a crashed worker simply stops renewing
and the deploy is claimed again, by this process after a restart or by another one.
"""

import asyncio
import logging
import os
import secrets
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.agents.client import Agents
from app.apps.services.facade import AppsFacade
from app.deploys.repositories.deploys import ACTIVE_STATUSES, Deploy
from app.deploys.services.runner import RunnerContext, process_deploy
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteWriter
from app.nodes.services.facade import NodesFacade

logger = logging.getLogger(__name__)


def new_worker_id() -> str:
    """Unique per process start: a restarted process must not look like its previous self."""
    return f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DeployWorker:
    def __init__(
        self,
        agents: Agents,
        uow_factory: Callable[[], DeploysUoW],
        apps: AppsFacade,
        nodes: NodesFacade,
        routes: RouteWriter,
        trusted_proxy: str,
        *,
        worker_id: str | None = None,
        concurrency: int = 4,
        lease: timedelta = timedelta(seconds=30),
        renew_every: float = 10.0,
        poll_interval: float = 1.0,
        build_poll_interval: float = 1.5,
        max_attempts: int = 3,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.worker_id = worker_id or new_worker_id()
        self._uow_factory = uow_factory
        self._ctx = RunnerContext(
            agents=agents,
            uow_factory=uow_factory,
            apps=apps,
            nodes=nodes,
            routes=routes,
            trusted_proxy=trusted_proxy,
            owner=self.worker_id,
            poll_interval=build_poll_interval,
            max_attempts=max_attempts,
        )
        self._concurrency = concurrency
        self._lease = lease
        self._renew_every = renew_every
        self._poll_interval = poll_interval
        self._clock = clock

        self._loop_task: asyncio.Task[None] | None = None
        self._handlers: dict[str, asyncio.Task[None]] = {}
        self._held: set[str] = set()  # leases to hand back on shutdown
        self._stopping = False

    def start(self) -> None:
        """Start polling in the background."""
        self._loop_task = asyncio.create_task(self._run(), name="deploy-worker")

    async def stop(self) -> None:
        """Cancel running deploys and release their leases so a restart picks them up at once."""
        self._stopping = True
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        handlers = list(self._handlers.values())
        for task in handlers:
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)
        for deploy_id in list(self._held):
            await self._release(deploy_id)

    async def tick(self) -> int:
        """Claim deploys while there are free slots; return how many were started."""
        started = 0
        while len(self._handlers) < self._concurrency:
            deploy = await self._claim()
            if deploy is None:
                break
            self._spawn(deploy)
            started += 1
        return started

    async def join(self) -> None:
        """Wait until every running deploy has been processed (tests)."""
        while self._handlers:
            await asyncio.gather(*self._handlers.values(), return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("deploy worker: claim failed")
            await asyncio.sleep(self._poll_interval)

    async def _claim(self) -> Deploy | None:
        async with self._uow_factory() as uow:
            deploy = await uow.deploys.claim(self.worker_id, self._lease, self._clock())
            if deploy is not None:
                await uow.commit()
            return deploy

    def _spawn(self, deploy: Deploy) -> None:
        # A claimed deploy is held from the moment of the claim until it is handled.
        self._held.add(deploy.id)
        task = asyncio.create_task(self._handle(deploy), name=f"deploy-{deploy.id}")
        self._handlers[deploy.id] = task
        task.add_done_callback(lambda _: self._handlers.pop(deploy.id, None))

    async def _handle(self, deploy: Deploy) -> None:
        logger.info(
            "deploy %s: claimed as %s (attempt %d, status %s)",
            deploy.id,
            self.worker_id,
            deploy.attempts,
            deploy.status,
        )
        work = asyncio.create_task(process_deploy(self._ctx, deploy))
        beat = asyncio.create_task(self._heartbeat(deploy.id, work))
        try:
            await asyncio.wait({work})
        except asyncio.CancelledError:  # shutdown: keep the lease in _held for release
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            raise
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)

        self._held.discard(deploy.id)
        if work.cancelled():
            logger.warning("deploy %s: lease lost, stopped", deploy.id)
        elif (error := work.exception()) is not None:
            logger.error("deploy %s: worker step failed", deploy.id, exc_info=error)

    async def _heartbeat(self, deploy_id: str, work: asyncio.Task[None]) -> None:
        """Renew the lease; when it is gone, stop the work (fencing)."""
        while True:
            await asyncio.sleep(self._renew_every)
            try:
                async with self._uow_factory() as uow:
                    renewed = await uow.deploys.renew(
                        deploy_id, self.worker_id, self._lease, self._clock()
                    )
                    await uow.commit()
            except Exception:
                logger.warning("deploy %s: lease renewal failed", deploy_id, exc_info=True)
                continue
            if not renewed:
                if await self._is_finished(deploy_id):
                    return  # the final write cleared the lease; the work is only cleaning up
                logger.warning("deploy %s: lease was taken, cancelling work", deploy_id)
                work.cancel()
                return

    async def _is_finished(self, deploy_id: str) -> bool:
        try:
            async with self._uow_factory() as uow:
                deploy = await uow.deploys.get(deploy_id)
        except Exception:
            return False
        return (
            deploy is not None
            and deploy.status not in ACTIVE_STATUSES
            and deploy.lease_owner == ""
        )

    async def _release(self, deploy_id: str) -> None:
        """Hand the lease back; a graceful stop is not a failed attempt."""
        try:
            async with self._uow_factory() as uow:
                deploy = await uow.deploys.get(deploy_id)
                if deploy is None:
                    return
                await uow.deploys.update_owned(
                    deploy_id,
                    self.worker_id,
                    lease_until=None,
                    attempts=max(deploy.attempts - 1, 0),
                )
                await uow.commit()
        except Exception:
            logger.warning("deploy %s: could not release the lease", deploy_id, exc_info=True)
