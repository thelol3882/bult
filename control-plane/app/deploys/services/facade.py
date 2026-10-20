"""The deploys domain's public API for other domains (enforced by import-linter)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.deploys.uow import DeploysUoW
from app.nodes.services.facade import NodesFacade

__all__ = ["DeploysFacade", "ReplicaOwner"]


@dataclass(frozen=True)
class ReplicaOwner:
    """Which app a running replica belongs to, and where it runs."""

    app_name: str
    index: int
    node: str


class DeploysFacade:
    def __init__(self, uow_factory: Callable[[], DeploysUoW], nodes: NodesFacade) -> None:
        self._uow_factory = uow_factory
        self._nodes = nodes

    async def replica_owners(self, replica_ids: Iterable[str]) -> dict[str, ReplicaOwner]:
        """System read: the owner of each *running* replica id; unknown ids are absent."""
        async with self._uow_factory() as uow:
            replicas = await uow.replicas.get_running(replica_ids)
            app_of: dict[str, str] = {}
            for deploy_id in {r.deploy_id for r in replicas}:
                deploy = await uow.deploys.get(deploy_id)
                if deploy is not None:
                    app_of[deploy_id] = deploy.app_name
        return {
            r.id: ReplicaOwner(app_of[r.deploy_id], r.index, r.node)
            for r in replicas
            if r.deploy_id in app_of
        }

    async def ready_replicas(self, app_name: str) -> int:
        """System read: replicas of the app's current running deploy on ready nodes."""
        async with self._uow_factory() as uow:
            running = await uow.deploys.list_running(app_name)
            if not running:
                return 0
            replicas = await uow.replicas.list_running([running[0].id])
        ready = {n.name for n in await self._nodes.runners() if n.ready}
        return sum(r.node in ready for r in replicas)
