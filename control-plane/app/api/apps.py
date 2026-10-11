"""Apps resource: create / list / get / delete."""

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AppStoreDep, DeployStoreDep, RoutesDep, SettingsDep
from app.schemas.app import AppCreate, AppOut
from app.services.apps import AppNameTakenError, AppNotFoundError
from app.services.nginx import RouteApplyError, running_routes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apps", tags=["apps"])


@router.post("", response_model=AppOut, status_code=status.HTTP_201_CREATED)
async def create_app(
    payload: AppCreate,
    store: AppStoreDep,
) -> AppOut:
    try:
        return store.create(payload)
    except AppNameTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"App with name '{payload.name}' already exists.",
        )


@router.get("", response_model=list[AppOut])
async def list_apps(
    store: AppStoreDep,
) -> list[AppOut]:
    return store.list()


@router.get("/{name}", response_model=AppOut)
async def get_app(
    name: str,
    store: AppStoreDep,
) -> AppOut:
    try:
        return store.get(name)
    except AppNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"App '{name}' not found.",
        )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(
    name: str,
    store: AppStoreDep,
    deploys: DeployStoreDep,
    routes: RoutesDep,
    settings: SettingsDep,
) -> None:
    try:
        store.delete(name)
    except AppNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"App '{name}' not found.",
        )

    deploys.remove_app(name)

    async with routes.lock:
        desired = running_routes(deploys, settings.runner_addrs)
        try:
            gen = routes.apply(desired)
            await routes.wait_applied(gen)
        except (RouteApplyError, TimeoutError) as e:
            logger.warning("delete %s: route update failed: %r", name, e)
