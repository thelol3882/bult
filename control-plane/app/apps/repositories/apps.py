"""App storage behind a Protocol (in-memory until PostgreSQL storage lands)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class App:
    """An app as the domain sees it."""

    name: str
    preset: str
    repo_url: str
    branch: str
    subdir: str
    created_at: datetime


class AppRepository(Protocol):
    """Storage only; domain rules live in AppService."""

    def add(self, app: App) -> None: ...
    def get(self, name: str) -> App | None: ...
    def list(self) -> list[App]: ...
    def delete(self, name: str) -> bool:
        """True if the app existed."""
        ...


class InMemoryAppRepository:
    """Dict keyed by name; also the test fake."""

    def __init__(self) -> None:
        self._apps: dict[str, App] = {}

    def add(self, app: App) -> None:
        self._apps[app.name] = app

    def get(self, name: str) -> App | None:
        return self._apps.get(name)

    def list(self) -> list[App]:
        return sorted(self._apps.values(), key=lambda a: a.name)

    def delete(self, name: str) -> bool:
        return self._apps.pop(name, None) is not None
