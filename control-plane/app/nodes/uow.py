"""Unit of Work of the nodes domain: one transaction over the domain's repositories."""

from collections.abc import Callable
from functools import partial
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.nodes.repositories.nodes import InMemoryNodeRepository, NodeRepository
from app.nodes.repositories.sql import SqlNodeRepository


class NodesUoW(Protocol):
    nodes: NodeRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...


class SqlNodesUoW:
    nodes: NodeRepository

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.nodes = SqlNodeRepository(self._session)
        return self

    async def commit(self) -> None:
        await self._session.commit()

    async def __aexit__(self, *exc: object) -> None:
        await self._session.rollback()
        await self._session.close()


class InMemoryNodesUoW:
    """Test fake: shares one repository across `with` blocks, records commits."""

    nodes: NodeRepository

    def __init__(self, repo: InMemoryNodeRepository | None = None) -> None:
        self.nodes = repo or InMemoryNodeRepository()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return

    async def commit(self) -> None:
        self.commits += 1


def sql_nodes_uow_factory(session_factory: async_sessionmaker) -> Callable[[], NodesUoW]:
    return partial(SqlNodesUoW, session_factory)
