"""Apps resource: create, list, get, delete."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.apps.deps import AppServiceDep
from app.apps.schemas.apps import AppCreate, AppOut, AppUpdate
from app.auth.deps import CurrentUser
from app.core.pagination import Page, PageParams

router = APIRouter(prefix="/apps", tags=["apps"])


@router.post("", response_model=AppOut, status_code=status.HTTP_201_CREATED)
async def create_app(
    payload: AppCreate, service: AppServiceDep, user: CurrentUser
) -> AppOut:
    app = await service.create(payload, user)
    return AppOut(**asdict(app), url=service.url(app))


@router.patch("/{name}", response_model=AppOut)
async def update_app(
    payload: AppUpdate, name: str, service: AppServiceDep, user: CurrentUser
) -> AppOut:
    app = await service.update(name, payload, user)
    return AppOut(**asdict(app), url=service.url(app))


@router.get("", response_model=Page[AppOut])
async def list_apps(
    service: AppServiceDep, user: CurrentUser, params: Annotated[PageParams, Query()]
) -> Page[AppOut]:
    apps, total = await service.list(params, user)
    return Page.build(
        [AppOut(**asdict(a), url=service.url(a)) for a in apps], total, params
    )


@router.get("/{name}", response_model=AppOut)
async def get_app(name: str, service: AppServiceDep, user: CurrentUser) -> AppOut:
    app = await service.get(name, user)
    return AppOut(**asdict(app), url=service.url(app))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(name: str, service: AppServiceDep, user: CurrentUser) -> None:
    await service.delete(name, user)
