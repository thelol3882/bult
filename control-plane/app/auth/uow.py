"""Unit of Work of the auth domain."""

from collections.abc import Callable
from functools import partial
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.repositories.sql import SqlUserRepository
from app.auth.repositories.users import InMemoryUserRepository, UserRepository


class AuthUoW(Protocol):
    users: UserRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...


class SqlAuthUoW:
    users: UserRepository

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = SqlUserRepository(self._session)
        return self

    async def commit(self) -> None:
        await self._session.commit()

    async def __aexit__(self, *exc: object) -> None:
        await self._session.rollback()
        await self._session.close()


class InMemoryAuthUoW:
    """Test fake: shares one repository across `with` blocks, records commits."""

    users: UserRepository

    def __init__(self, repo: InMemoryUserRepository | None = None) -> None:
        self.users = repo or InMemoryUserRepository()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return

    async def commit(self) -> None:
        self.commits += 1


def sql_auth_uow_factory(session_factory: async_sessionmaker) -> Callable[[], AuthUoW]:
    return partial(SqlAuthUoW, session_factory)
