"""Apps resource: create / list / get / delete."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AppStoreDep
from app.schemas.app import AppCreate, AppOut
from app.services.apps import AppNameTakenError, AppNotFoundError

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
) -> None:
    try:
        store.delete(name)
    except AppNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"App '{name}' not found.",
        )
