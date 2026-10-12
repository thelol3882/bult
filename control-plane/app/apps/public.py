"""Depends wiring of the apps facade for other domains (never import app.apps.deps)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.apps.deps import AppServiceDep
from app.apps.services.apps import AppService
from app.apps.services.facade import AppsFacade
from app.apps.uow import AppsUoW
from app.core.config import Settings
from app.core.events import EventCollector


def build_apps_facade(
    uow_factory: Callable[[], AppsUoW], settings: Settings, events: EventCollector
) -> AppsFacade:
    """The facade outside a request (event wiring)."""
    return AppsFacade(
        AppService(uow_factory=uow_factory, settings=settings, events=events)
    )


def get_apps_facade(service: AppServiceDep) -> AppsFacade:
    return AppsFacade(service)


AppsFacadeDep = Annotated[AppsFacade, Depends(get_apps_facade)]
