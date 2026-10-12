"""Depends wiring of the apps domain."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.apps.services.apps import AppService
from app.apps.uow import AppsUoW
from app.core.deps import EventCollectorDep, SettingsDep


def get_apps_uow_factory(request: Request) -> Callable[[], AppsUoW]:
    return request.app.state.apps_uow_factory


AppUoWDep = Annotated[Callable[[], AppsUoW], Depends(get_apps_uow_factory)]


def get_app_service(
    app_uow: AppUoWDep, settings: SettingsDep, events: EventCollectorDep
) -> AppService:
    return AppService(
        uow_factory=app_uow,
        settings=settings,
        events=events,
    )


AppServiceDep = Annotated[AppService, Depends(get_app_service)]
