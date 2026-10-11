"""Deploys of an app: start one (202) and read its status."""

import asyncio
import logging
import uuid
from functools import lru_cache
from pathlib import Path

import grpc
from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import AgentsDep, AppStoreDep, DeployStoreDep, RoutesDep, SettingsDep
from app.schemas.deploy import DeployOut
from app.services.apps import AppNotFoundError
from app.services.deploy_runner import run_deploy
from app.services.deploys import Deploy, DeployNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apps/{name}/deploys", tags=["deploys"])

PRESETS_DIR = Path(__file__).resolve().parents[2] / "presets"


@lru_cache
def _dockerfile(preset: str) -> str:
    """Dockerfile text of a preset; read once, then cached."""
    return (PRESETS_DIR / preset / "Dockerfile").read_text()


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DeployOut)
async def start_deploy(
    name: str,
    request: Request,
    apps: AppStoreDep,
    routes: RoutesDep,
    deploys: DeployStoreDep,
    agents: AgentsDep,
    settings: SettingsDep,
) -> Deploy:
    try:
        app = apps.get(name)
    except AppNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "app not found") from None

    deploy_id = uuid.uuid4().hex

    for attempt in (1, 2):
        try:
            _ = await agents.start_deploy(
                deploy_id=deploy_id,
                app_id=app.name,
                repo_url=str(app.repo_url),
                branch=app.branch,
                subdir=app.subdir,
                dockerfile=_dockerfile(app.preset),
            )
            break
        except grpc.aio.AioRpcError as e:
            code = e.code()
            if code == grpc.StatusCode.DEADLINE_EXCEEDED and attempt == 1:
                logger.warning("StartDeploy %s: deadline exceeded, retrying", deploy_id)
                continue
            if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                logger.warning(
                    "StartDeploy %s: %s %s", deploy_id, code.name, e.details()
                )
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "builder unavailable, try again",
                ) from None
            logger.error("StartDeploy %s: %s %s", deploy_id, code.name, e.details())
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "internal error"
            ) from None

    deploy = deploys.add(Deploy(id=deploy_id, app_name=app.name))

    task = asyncio.create_task(
        run_deploy(
            agents,
            deploys,
            routes,
            settings.runner_addrs,
            deploy_id,
            app.name,
            settings.trusted_proxy,
        )
    )
    tasks: set[asyncio.Task] = request.app.state.deploy_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)

    return deploy


@router.get("/{deploy_id}", response_model=DeployOut)
async def get_deploy(name: str, deploy_id: str, deploys: DeployStoreDep) -> Deploy:
    try:
        return deploys.get(name, deploy_id)
    except DeployNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "deploy not found") from None
