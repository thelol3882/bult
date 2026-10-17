"""Lifecycle of an app: stop, start from the last image, read the logs."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.auth.deps import CurrentUser
from app.deploys.deps import DeployServiceDep
from app.deploys.schemas.deploys import DeployOut, LogsOut

router = APIRouter(prefix="/apps/{name}", tags=["lifecycle"])


@router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_app(name: str, service: DeployServiceDep, user: CurrentUser) -> None:
    await service.stop_app(name, user)


@router.post("/start", status_code=status.HTTP_202_ACCEPTED, response_model=DeployOut)
async def start_app(
    name: str, service: DeployServiceDep, user: CurrentUser
) -> DeployOut:
    return DeployOut.model_validate(await service.start_app(name, user))


@router.get("/logs", response_model=LogsOut)
async def get_logs(
    name: str,
    service: DeployServiceDep,
    user: CurrentUser,
    tail: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> LogsOut:
    logs = await service.logs(name, tail, user)
    return LogsOut(deploy_id=logs.deploy_id, lines=logs.lines)
