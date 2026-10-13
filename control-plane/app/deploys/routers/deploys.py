"""Deploys of an app: start one (202) and read its status."""

from fastapi import APIRouter, status

from app.deploys.deps import DeployServiceDep
from app.deploys.schemas.deploys import DeployOut

router = APIRouter(prefix="/apps/{name}/deploys", tags=["deploys"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DeployOut)
async def start_deploy(name: str, service: DeployServiceDep) -> DeployOut:
    return DeployOut.model_validate(await service.start(name))


# TODO GET "" (history) → CursorPage[DeployOut], CursorParams:
#  1. before = decode_cursor(params.cursor) if params.cursor else None (bad cursor → 422 via the handler).
#  2. rows = await service.history(name, before, params.limit + 1)  (service checks the app exists → 404).
#  3. has_more = len(rows) > limit; page = rows[:limit];
#     next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more else None.
@router.get("/{deploy_id}", response_model=DeployOut)
async def get_deploy(name: str, deploy_id: str, service: DeployServiceDep) -> DeployOut:
    return DeployOut.model_validate(await service.get(name, deploy_id))
