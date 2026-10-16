"""Deploys domain rules and errors. Calls the apps domain through its facade, never its repository."""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime

from app.agents.client import Agents
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.errors import NotFoundError
from app.core.principal import Principal
from app.deploys.repositories.deploys import Deploy
from app.deploys.services.runner import remove_replica_quietly
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteApplyError, RouteWriter, running_routes

logger = logging.getLogger(__name__)


class DeployNotFoundError(NotFoundError):
    """No deploy with this id for this app."""

    code = ErrorCode.DEPLOY_NOT_FOUND

    def __init__(self, deploy_id: str) -> None:
        super().__init__(f"Deploy '{deploy_id}' not found.")


class DeployService:
    def __init__(
        self,
        uow_factory: Callable[[], DeploysUoW],
        apps: AppsFacade,
        agents: Agents,
        routes: RouteWriter,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._apps = apps
        self._agents = agents
        self._routes = routes
        self._settings = settings

    async def start(self, app_name: str, principal: Principal) -> Deploy:
        """Queue a deploy; the worker does the rest. DeployInProgressError if one is active."""
        app = await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            deploy = await uow.deploys.add(Deploy(id=uuid.uuid4().hex, app_name=app.name))
            await uow.commit()
        return deploy

    async def get(self, app_name: str, deploy_id: str, principal: Principal) -> Deploy:
        """DeployNotFoundError if missing OR if it belongs to another app."""
        await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            deploy = await uow.deploys.get(deploy_id)
            if deploy is None or deploy.app_name != app_name:
                raise DeployNotFoundError(deploy_id)
            return deploy

    async def history(
        self,
        app_name: str,
        before: tuple[datetime, str] | None,
        limit: int,
        principal: Principal,
    ) -> list[Deploy]:
        await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            return await uow.deploys.list_for_app(app_name, before, limit)

    async def remove_app(self, app_name: str) -> None:
        """Drop the app's routes and remove its replicas (failures are logged).

        Replicas are found by asking the nodes, not from deploy rows: the FK
        cascade has already deleted the rows when the app row was deleted.
        """
        async with self._uow_factory() as uow:
            await uow.deploys.delete_for_app(app_name)  # no-op after the cascade
            await uow.commit()

        # Routes first: stop sending traffic, then remove the replicas.
        # Always re-applied: a deploy in flight may have published this app's route already.
        gen: int | None = None
        async with self._routes.lock:
            async with self._uow_factory() as uow:
                deploys = await uow.deploys.list_all()
            desired = running_routes(deploys, self._settings.runners)
            try:
                gen = self._routes.apply(desired)
                await self._routes.wait_applied(gen)
            except (RouteApplyError, TimeoutError) as e:
                logger.warning("delete %s: route update failed: %r", app_name, e)

        found = 0
        removed = 0
        for node in self._agents.runner_names:
            try:
                replicas = await self._agents.list_replicas(node)
            except Exception:
                logger.warning(
                    "delete %s: could not list replicas on %s",
                    app_name,
                    node,
                    exc_info=True,
                )
                continue
            for replica in replicas:
                if replica.app_id != app_name:
                    continue
                found += 1
                if await remove_replica_quietly(self._agents, node, replica.replica_id):
                    removed += 1

        logger.info(
            "app %s deleted: %d replicas found, %d removed, route generation %s",
            app_name,
            found,
            removed,
            gen if gen is not None else "-",
        )
