"""Apps domain rules and errors."""

from collections.abc import Callable

from app.apps.errors import AppNameTakenError, AppNotFoundError
from app.apps.events import AppDeleted
from app.apps.repositories.apps import App
from app.apps.schemas.apps import AppCreate, AppUpdate
from app.apps.uow import AppsUoW
from app.core.config import Settings
from app.core.events import EventPublisher
from app.core.pagination import PageParams


class AppService:
    def __init__(
        self,
        uow_factory: Callable[[], AppsUoW],
        events: EventPublisher,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._events = events
        self._settings = settings

    async def create(self, data: AppCreate) -> App:
        async with self._uow_factory() as uow:
            if await uow.apps.get(data.name) is not None:
                raise AppNameTakenError(data.name)
            app = App(
                name=data.name,
                preset=data.preset,
                repo_url=str(data.repo_url),
                branch=data.branch,
                subdir=data.subdir,
            )
            app = await uow.apps.add(app)
            await uow.commit()
            return app

    async def get(self, name: str) -> App:
        async with self._uow_factory() as uow:
            app = await uow.apps.get(name)
            if app is None:
                raise AppNotFoundError(name)
            return app

    async def update(self, name: str, data: AppUpdate) -> App:
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return await self.get(name)

        if changes.get("repo_url") is not None:
            changes["repo_url"] = str(changes["repo_url"])

        async with self._uow_factory() as uow:
            result = await uow.apps.update(name, **changes)

            if result is None:
                raise AppNotFoundError(name)

            await uow.commit()
            return result

    async def list(self, params: PageParams) -> tuple[list[App], int]:
        async with self._uow_factory() as uow:
            total = await uow.apps.count()
            apps = await uow.apps.list(params.offset, params.page_size)
            return apps, total

    async def delete(self, name: str) -> None:
        """Delete the app; subscribers of AppDeleted clean up the rest."""
        async with self._uow_factory() as uow:
            if not await uow.apps.delete(name):
                raise AppNotFoundError(name)
            await uow.commit()
            self._events.publish(AppDeleted(name))

    def url(self, app: App) -> str:
        """Public address of the app."""
        return f"{self._settings.apps_scheme}://{app.name}.{self._settings.apps_domain}"
