"""The apps domain's public API for other domains (enforced by import-linter)."""

from app.apps.repositories.apps import App
from app.apps.services.apps import AppNameTakenError, AppNotFoundError, AppService

__all__ = ["App", "AppNameTakenError", "AppNotFoundError", "AppsFacade"]


class AppsFacade:
    def __init__(self, service: AppService) -> None:
        self._service = service

    def get_app(self, name: str) -> App:
        return self._service.get(name)
