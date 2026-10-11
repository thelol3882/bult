"""Apps domain rules and errors."""

from datetime import UTC, datetime

from app.apps.events import AppDeleted
from app.apps.repositories.apps import App, AppRepository
from app.apps.schemas.apps import AppCreate
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.errors import ConflictError, NotFoundError
from app.core.events import EventPublisher


class AppNameTakenError(ConflictError):
    """An app with this name already exists."""

    code = ErrorCode.APP_NAME_TAKEN

    def __init__(self, name: str) -> None:
        super().__init__(f"App with name '{name}' already exists.", field="name")


class AppNotFoundError(NotFoundError):
    """No app with this name."""

    code = ErrorCode.APP_NOT_FOUND

    def __init__(self, name: str) -> None:
        super().__init__(f"App '{name}' not found.")


class AppService:
    def __init__(
        self, repo: AppRepository, settings: Settings, events: EventPublisher
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._events = events

    def create(self, data: AppCreate) -> App:
        if self._repo.get(data.name) is not None:
            raise AppNameTakenError(data.name)

        app = App(
            name=data.name,
            preset=data.preset,
            repo_url=str(data.repo_url),
            branch=data.branch,
            subdir=data.subdir,
            created_at=datetime.now(UTC),
        )
        self._repo.add(app)
        return app

    def get(self, name: str) -> App:
        app = self._repo.get(name)
        if app is None:
            raise AppNotFoundError(name)
        return app

    def list(self) -> list[App]:
        return self._repo.list()

    def delete(self, name: str) -> None:
        """Delete the app; subscribers of AppDeleted clean up the rest."""
        if not self._repo.delete(name):
            raise AppNotFoundError(name)
        self._events.publish(AppDeleted(name))

    def url(self, app: App) -> str:
        """Public address of the app."""
        return f"{self._settings.apps_scheme}://{app.name}.{self._settings.apps_domain}"
