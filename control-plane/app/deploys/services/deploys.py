"""Deploys domain rules and errors. Calls the apps domain through its facade, never its repository."""

import asyncio
import logging
import uuid
from functools import lru_cache
from pathlib import Path

import grpc

from app.agents.client import Agents
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.errors import InternalError, NotFoundError, ServiceUnavailableError
from app.deploys.repositories.deploys import Deploy, DeployRepository
from app.deploys.services.runner import run_deploy
from app.ingress.routes import RouteWriter

logger = logging.getLogger(__name__)

PRESETS_DIR = Path(__file__).resolve().parents[3] / "presets"


class DeployNotFoundError(NotFoundError):
    """No deploy with this id for this app."""

    code = ErrorCode.DEPLOY_NOT_FOUND

    def __init__(self, deploy_id: str) -> None:
        super().__init__(f"Deploy '{deploy_id}' not found.")


class BuilderUnavailableError(ServiceUnavailableError):
    """StartDeploy: UNAVAILABLE, or DEADLINE_EXCEEDED twice."""

    code = ErrorCode.BUILDER_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("builder unavailable, try again")


class DeployRejectedError(InternalError):
    """StartDeploy: any other gRPC code (our bug; details only in the log)."""

    def __init__(self) -> None:
        super().__init__("internal error")


@lru_cache
def _dockerfile(preset: str) -> str:
    """Dockerfile text of a preset (cached)."""
    return (PRESETS_DIR / preset / "Dockerfile").read_text()


class DeployService:
    def __init__(
        self,
        repo: DeployRepository,
        apps: AppsFacade,
        agents: Agents,
        routes: RouteWriter,
        settings: Settings,
        tasks: set[asyncio.Task[None]],
    ) -> None:
        self._repo = repo
        self._apps = apps
        self._agents = agents
        self._routes = routes
        self._settings = settings
        self._tasks = tasks

    async def start(self, app_name: str) -> Deploy:
        """Start the build on the builder, then run the rest in a background task."""
        app = self._apps.get_app(app_name)

        # The id is generated before the call so a retry reaches the same job.
        deploy_id = uuid.uuid4().hex

        for attempt in (1, 2):
            try:
                _ = await self._agents.start_deploy(
                    deploy_id=deploy_id,
                    app_id=app.name,
                    repo_url=app.repo_url,
                    branch=app.branch,
                    subdir=app.subdir,
                    dockerfile=_dockerfile(app.preset),
                )
                break
            except grpc.aio.AioRpcError as e:
                code = e.code()
                if code == grpc.StatusCode.DEADLINE_EXCEEDED and attempt == 1:
                    logger.warning(
                        "StartDeploy %s: deadline exceeded, retrying", deploy_id
                    )
                    continue
                if code in (
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                ):
                    logger.warning(
                        "StartDeploy %s: %s %s", deploy_id, code.name, e.details()
                    )
                    raise BuilderUnavailableError() from None
                logger.error("StartDeploy %s: %s %s", deploy_id, code.name, e.details())
                raise DeployRejectedError() from None

        deploy = self._repo.add(Deploy(id=deploy_id, app_name=app.name))

        task = asyncio.create_task(
            run_deploy(
                self._agents,
                self._repo,
                self._routes,
                self._settings.runners,
                deploy_id,
                app.name,
                self._settings.trusted_proxy,
            )
        )
        # The loop holds only a weak reference to tasks.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return deploy

    def get(self, app_name: str, deploy_id: str) -> Deploy:
        """DeployNotFoundError if missing OR if it belongs to another app."""
        deploy = self._repo.get(deploy_id)
        if deploy is None or deploy.app_name != app_name:
            raise DeployNotFoundError(deploy_id)
        return deploy
