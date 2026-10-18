"""Lifecycle of an app: stop, start from the last image, read the logs."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.auth.deps import CurrentUser
from app.deploys.deps import DeployServiceDep
from app.core.config import MAX_REPLICAS
from app.deploys.schemas.deploys import DeployOut, LogsOut, ReplicasOut, ReplicasUpdate

router = APIRouter(prefix="/apps/{name}", tags=["lifecycle"])


@router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_app(name: str, service: DeployServiceDep, user: CurrentUser) -> None:
    await service.stop_app(name, user)


@router.post("/start", status_code=status.HTTP_202_ACCEPTED, response_model=DeployOut)
async def start_app(
    name: str, service: DeployServiceDep, user: CurrentUser
) -> DeployOut:
    return DeployOut.model_validate(await service.start_app(name, user))


@router.put("/replicas", response_model=ReplicasOut)
async def set_replicas(
    payload: ReplicasUpdate, name: str, service: DeployServiceDep, user: CurrentUser
) -> ReplicasOut:
    """Scale the running deploy without a build; 0 stops the app."""
    scaled = await service.scale_app(name, payload.replicas, user)
    return ReplicasOut(
        replicas=scaled.replicas,
        deploy=None if scaled.deploy is None else DeployOut.model_validate(scaled.deploy),
    )


@router.get("/logs", response_model=LogsOut)
async def get_logs(
    name: str,
    service: DeployServiceDep,
    user: CurrentUser,
    tail: Annotated[int, Query(ge=1, le=1000)] = 200,
    replica: Annotated[int | None, Query(ge=0, lt=MAX_REPLICAS)] = None,
) -> LogsOut:
    logs = await service.logs(name, tail, user, replica)
    return LogsOut(deploy_id=logs.deploy_id, replica=logs.replica, lines=logs.lines)
