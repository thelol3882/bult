"""Deploys of an app: start one (202) and read its status."""

from fastapi import APIRouter, status

from app.deploys.deps import DeployServiceDep
from app.deploys.schemas.deploys import DeployOut

router = APIRouter(prefix="/apps/{name}/deploys", tags=["deploys"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DeployOut)
async def start_deploy(name: str, service: DeployServiceDep) -> DeployOut:
    return DeployOut.model_validate(await service.start(name))


@router.get("/{deploy_id}", response_model=DeployOut)
async def get_deploy(name: str, deploy_id: str, service: DeployServiceDep) -> DeployOut:
    return DeployOut.model_validate(await service.get(name, deploy_id))
