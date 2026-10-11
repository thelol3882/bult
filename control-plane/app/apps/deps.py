"""Depends wiring of the apps domain."""

from typing import Annotated

from fastapi import Depends, Request

from app.apps.repositories.apps import AppRepository
from app.apps.services.apps import AppService
from app.core.deps import EventCollectorDep, SettingsDep


def get_app_repo(request: Request) -> AppRepository:
    """The app repository."""
    return request.app.state.app_repo


AppRepoDep = Annotated[AppRepository, Depends(get_app_repo)]


def get_app_service(
    repo: AppRepoDep, settings: SettingsDep, events: EventCollectorDep
) -> AppService:
    return AppService(repo, settings, events)


AppServiceDep = Annotated[AppService, Depends(get_app_service)]
