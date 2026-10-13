"""App storage behind a Protocol."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from uuid_utils.compat import uuid7


@dataclass(frozen=True)
class App:
    """An app as the domain sees it."""

    name: str
    preset: str
    repo_url: str
    branch: str
    subdir: str
    id: UUID | None = None
    created_at: datetime | None = None


class AppRepository(Protocol):
    """Storage only; domain rules live in AppService."""

    async def add(self, app: App) -> App: ...
    async def get(self, name: str) -> App | None: ...
    async def update(self, name: str, **changes) -> App | None: ...
    async def count(self) -> int: ...
    async def list(self, offset: int, limit: int) -> list[App]: ...
    async def delete(self, name: str) -> bool:
        """True if the app existed."""
        ...


class InMemoryAppRepository:
    """Dict keyed by name; also the test fake."""

    def __init__(self) -> None:
        self._apps: dict[str, App] = {}

    async def add(self, app: App) -> App:
        app = replace(app, id=uuid7(), created_at=datetime.now(UTC))
        self._apps[app.name] = app
        return app

    async def get(self, name: str) -> App | None:
        return self._apps.get(name)

    async def update(self, name: str, **changes) -> App | None:
        if name not in self._apps:
            return None

        app = self._apps[name]
        updated_app = replace(app, **changes)
        self._apps[name] = updated_app
        return updated_app

    async def count(self) -> int:
        return len(self._apps)

    async def list(self, offset: int, limit: int) -> list[App]:
        return sorted(self._apps.values(), key=lambda a: a.name)[
            offset : offset + limit
        ]

    async def delete(self, name: str) -> bool:
        return self._apps.pop(name, None) is not None
