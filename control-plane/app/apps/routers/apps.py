"""Apps resource: create, list, get, delete."""

from dataclasses import asdict

from fastapi import APIRouter, status

from app.apps.deps import AppServiceDep
from app.apps.schemas.apps import AppCreate, AppOut

router = APIRouter(prefix="/apps", tags=["apps"])


@router.post("", response_model=AppOut, status_code=status.HTTP_201_CREATED)
async def create_app(payload: AppCreate, service: AppServiceDep) -> AppOut:
    app = await service.create(payload)
    return AppOut(**asdict(app), url=service.url(app))


@router.get("", response_model=list[AppOut])
async def list_apps(service: AppServiceDep) -> list[AppOut]:
    return [AppOut(**asdict(app), url=service.url(app)) for app in await service.list()]


@router.get("/{name}", response_model=AppOut)
async def get_app(name: str, service: AppServiceDep) -> AppOut:
    app = await service.get(name)
    return AppOut(**asdict(app), url=service.url(app))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(name: str, service: AppServiceDep) -> None:
    await service.delete(name)
