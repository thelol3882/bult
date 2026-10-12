"""Unit of Work of the apps domain: one transaction over the domain's repositories."""

from collections.abc import Callable
from functools import partial
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.apps.repositories.apps import AppRepository, InMemoryAppRepository
from app.apps.repositories.sql import SqlAppRepository


class AppsUoW(Protocol):
    apps: AppRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...


class SqlAppsUoW:
    apps: AppRepository

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.apps = SqlAppRepository(self._session)
        return self

    async def commit(self) -> None:
        await self._session.commit()

    async def __aexit__(self, *exc: object) -> None:
        await self._session.rollback()
        await self._session.close()


class InMemoryAppsUoW:
    """Test fake: shares one repository across `with` blocks, records commits."""

    apps: AppRepository

    def __init__(self, repo: InMemoryAppRepository | None = None) -> None:
        self.apps = repo or InMemoryAppRepository()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return

    async def commit(self) -> None:
        self.commits += 1


def sql_apps_uow_factory(session_factory: async_sessionmaker) -> Callable[[], AppsUoW]:
    return partial(SqlAppsUoW, session_factory)
