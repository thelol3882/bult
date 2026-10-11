"""Depends wiring of the apps facade for other domains (never import app.apps.deps)."""

from typing import Annotated

from fastapi import Depends

from app.apps.deps import AppServiceDep
from app.apps.services.facade import AppsFacade


def get_apps_facade(service: AppServiceDep) -> AppsFacade:
    return AppsFacade(service)


AppsFacadeDep = Annotated[AppsFacade, Depends(get_apps_facade)]
