"""Unit of Work of the deploys domain: one transaction over the domain's repositories."""

from collections.abc import Callable
from functools import partial
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.deploys.repositories.deploys import DeployRepository, InMemoryDeployRepository
from app.deploys.repositories.sql import SqlDeployRepository


class DeploysUoW(Protocol):
    deploys: DeployRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...


class SqlDeploysUoW:
    deploys: DeployRepository

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.deploys = SqlDeployRepository(self._session)
        return self

    async def commit(self) -> None:
        await self._session.commit()

    async def __aexit__(self, *exc: object) -> None:
        await self._session.rollback()
        await self._session.close()


class InMemoryDeploysUoW:
    """Test fake: shares one repository across `with` blocks, records commits."""

    deploys: DeployRepository

    def __init__(self, repo: InMemoryDeployRepository | None = None) -> None:
        self.deploys = repo or InMemoryDeployRepository()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return

    async def commit(self) -> None:
        self.commits += 1


def sql_deploys_uow_factory(
    session_factory: async_sessionmaker,
) -> Callable[[], DeploysUoW]:
    return partial(SqlDeploysUoW, session_factory)
