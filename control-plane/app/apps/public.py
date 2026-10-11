"""Depends wiring of the apps facade for other domains (never import app.apps.deps)."""

from typing import Annotated

from fastapi import Depends

from app.apps.deps import AppServiceDep
from app.apps.repositories.apps import AppRepository
from app.apps.services.apps import AppService
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.core.events import EventCollector


def build_apps_facade(
    repo: AppRepository, settings: Settings, events: EventCollector
) -> AppsFacade:
    """The facade outside a request (event wiring)."""
    return AppsFacade(AppService(repo, settings, events))


def get_apps_facade(service: AppServiceDep) -> AppsFacade:
    return AppsFacade(service)


AppsFacadeDep = Annotated[AppsFacade, Depends(get_apps_facade)]
