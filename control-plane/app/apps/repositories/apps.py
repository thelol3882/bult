"""App storage behind a Protocol."""

from dataclasses import dataclass, field, replace
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
    owner_id: UUID | None = None
    id: UUID | None = None
    created_at: datetime | None = None
    replicas: int = 1  # desired state: 1 = running, 0 = stopped
    # Secret values: kept out of repr so they cannot reach a log line.
    env: dict[str, str] = field(default_factory=dict, repr=False)


class AppRepository(Protocol):
    """Storage only; domain rules live in AppService."""

    async def add(self, app: App) -> App: ...
    async def get(self, name: str) -> App | None: ...
    async def update(self, name: str, **changes) -> App | None: ...
    async def count(self, owner_id: UUID) -> int: ...
    async def list_stopped(self) -> list[str]:
        """Names of the apps with replicas == 0."""
        ...
    async def list(self, owner_id: UUID, offset: int, limit: int) -> list[App]: ...
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

    def _owned(self, owner_id: UUID) -> list[App]:
        return [a for a in self._apps.values() if a.owner_id == owner_id]

    async def count(self, owner_id: UUID) -> int:
        return len(self._owned(owner_id))

    async def list_stopped(self) -> list[str]:
        return sorted(a.name for a in self._apps.values() if a.replicas == 0)

    async def list(self, owner_id: UUID, offset: int, limit: int) -> list[App]:
        return sorted(self._owned(owner_id), key=lambda a: a.name)[
            offset : offset + limit
        ]

    async def delete(self, name: str) -> bool:
        return self._apps.pop(name, None) is not None
