"""The apps domain's public API for other domains (enforced by import-linter)."""

from app.apps.errors import AppForbiddenError, AppNameTakenError, AppNotFoundError
from app.apps.repositories.apps import App
from app.apps.services.apps import AppService
from app.core.principal import Principal

__all__ = [
    "App",
    "AppForbiddenError",
    "AppNameTakenError",
    "AppNotFoundError",
    "AppsFacade",
]


class AppsFacade:
    def __init__(self, service: AppService) -> None:
        self._service = service

    async def get_app(self, name: str, principal: Principal) -> App:
        """The app if the principal owns it (AppNotFoundError / AppForbiddenError otherwise)."""
        return await self._service.get(name, principal)
