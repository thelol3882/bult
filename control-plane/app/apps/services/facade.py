"""The apps domain's public API for other domains (enforced by import-linter)."""

from app.apps.errors import AppForbiddenError, AppNameTakenError, AppNotFoundError
from app.apps.repositories.apps import App, AppRoute
from app.apps.services.apps import AppService
from app.core.principal import Principal

__all__ = [
    "App",
    "AppForbiddenError",
    "AppNameTakenError",
    "AppNotFoundError",
    "AppRoute",
    "AppsFacade",
]


class AppsFacade:
    def __init__(self, service: AppService) -> None:
        self._service = service

    async def get_app(self, name: str, principal: Principal) -> App:
        """The app if the principal owns it (AppNotFoundError / AppForbiddenError otherwise)."""
        return await self._service.get(name, principal)

    async def get_app_unchecked(self, name: str) -> App:
        """System read for background work: no principal, AppNotFoundError if gone."""
        return await self._service.get_unchecked(name)

    async def set_replicas(self, name: str, replicas: int, principal: Principal) -> App:
        """Set the desired replica count (0 = stopped, 1 = running) of an app the principal owns."""
        return await self._service.set_replicas(name, replicas, principal)

    async def path_routes(self) -> dict[str, tuple[AppRoute, ...]]:
        """System read: the path routes of every app, by app name."""
        return await self._service.path_routes()

    async def stopped_app_names(self) -> list[str]:
        """System read: names of the apps whose desired replica count is 0."""
        return await self._service.stopped_names()
