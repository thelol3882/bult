"""Deploys of an app: start one (202) and read its status."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.pagination import CursorPage, CursorParams, decode_cursor, encode_cursor
from app.deploys.deps import DeployServiceDep
from app.deploys.schemas.deploys import DeployOut

router = APIRouter(prefix="/apps/{name}/deploys", tags=["deploys"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DeployOut)
async def start_deploy(name: str, service: DeployServiceDep) -> DeployOut:
    return DeployOut.model_validate(await service.start(name))


@router.get("", response_model=CursorPage[DeployOut])
async def get_history(
    name: str, service: DeployServiceDep, params: Annotated[CursorParams, Query()]
) -> CursorPage[DeployOut]:
    before = decode_cursor(params.cursor) if params.cursor else None
    rows = await service.history(name, before, params.limit + 1)
    has_more = len(rows) > params.limit
    page = rows[: params.limit]

    next_cursor = None
    
    if has_more:
        assert page[-1].created_at is not None
        next_cursor = encode_cursor(page[-1].created_at, page[-1].id)

    return CursorPage[DeployOut](
        results=[DeployOut.model_validate(p) for p in page], next_cursor=next_cursor
    )


@router.get("/{deploy_id}", response_model=DeployOut)
async def get_deploy(name: str, deploy_id: str, service: DeployServiceDep) -> DeployOut:
    return DeployOut.model_validate(await service.get(name, deploy_id))
