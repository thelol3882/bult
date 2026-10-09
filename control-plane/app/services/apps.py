"""In-memory app store. Replaced by PostgreSQL in lesson 18 — the routers
must not notice: they only see this interface through a dependency."""

from datetime import UTC, datetime

from app.schemas.app import AppCreate, AppOut


class AppNameTakenError(Exception):
    """An app with this name already exists (→ HTTP 409)."""


class AppNotFoundError(Exception):
    """No app with this name (→ HTTP 404)."""


class AppStore:
    """Apps kept in a dict, keyed by name."""

    def __init__(self) -> None:
        self._apps: dict[str, AppOut] = {}

    def create(self, data: AppCreate) -> AppOut:
        """Add an app; AppNameTakenError if the name exists."""
        if data.name in self._apps:
            raise AppNameTakenError(f"App with name '{data.name}' already exists.")

        app = AppOut(
            name=data.name,
            preset=data.preset,
            repo_url=str(data.repo_url),
            branch=data.branch,
            subdir=data.subdir,
            created_at=datetime.now(UTC),
        )
        self._apps[data.name] = app
        return app

    def get(self, name: str) -> AppOut:
        """AppNotFoundError if missing."""
        app = self._apps.get(name)
        if app is None:
            raise AppNotFoundError(f"App '{name}' not found.")
        return app

    def list(self) -> list[AppOut]:
        """All apps, sorted by name."""
        return sorted(self._apps.values(), key=lambda a: a.name)

    def delete(self, name: str) -> None:
        """AppNotFoundError if missing."""
        if name not in self._apps:
            raise AppNotFoundError(f"App '{name}' not found.")
        del self._apps[name]
