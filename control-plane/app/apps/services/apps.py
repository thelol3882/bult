"""Apps domain rules and errors."""

from collections.abc import Callable

from app.apps.errors import AppForbiddenError, AppNameTakenError, AppNotFoundError
from app.apps.events import AppDeleted
from app.apps.repositories.apps import App
from app.apps.schemas.apps import AppCreate, AppUpdate
from app.apps.uow import AppsUoW
from app.core.config import Settings
from app.core.events import EventPublisher
from app.core.pagination import PageParams
from app.core.principal import Principal


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

    async def create(self, data: AppCreate, principal: Principal) -> App:
        async with self._uow_factory() as uow:
            if await uow.apps.get(data.name) is not None:
                raise AppNameTakenError(data.name)
            app = App(
                name=data.name,
                preset=data.preset,
                repo_url=str(data.repo_url),
                branch=data.branch,
                subdir=data.subdir,
                owner_id=principal.id,
            )
            app = await uow.apps.add(app)
            await uow.commit()
            return app

    async def get(self, name: str, principal: Principal) -> App:
        async with self._uow_factory() as uow:
            return await self._owned(uow, name, principal)

    async def get_unchecked(self, name: str) -> App:
        """System read without an ownership check (background work on an already authorized request)."""
        async with self._uow_factory() as uow:
            app = await uow.apps.get(name)
            if app is None:
                raise AppNotFoundError(name)
            return app

    async def update(self, name: str, data: AppUpdate, principal: Principal) -> App:
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return await self.get(name, principal)

        if changes.get("repo_url") is not None:
            changes["repo_url"] = str(changes["repo_url"])

        async with self._uow_factory() as uow:
            await self._owned(uow, name, principal)
            result = await uow.apps.update(name, **changes)

            if result is None:
                raise AppNotFoundError(name)

            await uow.commit()
            return result

    async def list(
        self, params: PageParams, principal: Principal
    ) -> tuple[list[App], int]:
        """The caller's apps and their total count."""
        async with self._uow_factory() as uow:
            total = await uow.apps.count(principal.id)
            apps = await uow.apps.list(principal.id, params.offset, params.page_size)
            return apps, total

    async def delete(self, name: str, principal: Principal) -> None:
        """Delete the app; subscribers of AppDeleted clean up the rest."""
        async with self._uow_factory() as uow:
            await self._owned(uow, name, principal)
            if not await uow.apps.delete(name):
                raise AppNotFoundError(name)
            await uow.commit()
            self._events.publish(AppDeleted(name))

    @staticmethod
    async def _owned(uow: AppsUoW, name: str, principal: Principal) -> App:
        """The app, or AppNotFoundError / AppForbiddenError if it is another user's."""
        app = await uow.apps.get(name)
        if app is None:
            raise AppNotFoundError(name)
        if app.owner_id != principal.id:
            raise AppForbiddenError(name)
        return app

    def url(self, app: App) -> str:
        """Public address of the app."""
        return f"{self._settings.apps_scheme}://{app.name}.{self._settings.apps_domain}"
