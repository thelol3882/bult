"""App storage behind a Protocol."""

import dataclasses
from dataclasses import dataclass
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
    async def list(self) -> list[App]: ...
    async def delete(self, name: str) -> bool:
        """True if the app existed."""
        ...


class InMemoryAppRepository:
    """Dict keyed by name; also the test fake."""

    def __init__(self) -> None:
        self._apps: dict[str, App] = {}

    async def add(self, app: App) -> App:
        app = dataclasses.replace(app, id=uuid7(), created_at=datetime.now(UTC))
        self._apps[app.name] = app
        return app

    async def get(self, name: str) -> App | None:
        return self._apps.get(name)

    async def list(self) -> list[App]:
        return sorted(self._apps.values(), key=lambda a: a.name)

    async def delete(self, name: str) -> bool:
        return self._apps.pop(name, None) is not None
