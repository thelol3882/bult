"""Unit of Work of the metrics domain: one transaction over the domain's repositories."""

from collections.abc import Callable
from functools import partial
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.metrics.repositories.metrics import (
    InMemoryMetricsRepository,
    MetricsRepository,
    ReplicaSample,
)
from app.metrics.repositories.sql import SqlMetricsRepository


class MetricsUoW(Protocol):
    metrics: MetricsRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...


class SqlMetricsUoW:
    metrics: MetricsRepository

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.metrics = SqlMetricsRepository(self._session)
        return self

    async def commit(self) -> None:
        await self._session.commit()

    async def __aexit__(self, *exc: object) -> None:
        await self._session.rollback()
        await self._session.close()


class InMemoryMetricsUoW:
    """Test fake: shares one repository across `with` blocks, records commits."""

    metrics: MetricsRepository

    def __init__(self) -> None:
        self._repo = InMemoryMetricsRepository()
        self.metrics = self._repo
        self.commits = 0

    @property
    def samples(self) -> list[ReplicaSample]:
        return self._repo.samples

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return

    async def commit(self) -> None:
        self.commits += 1


def sql_metrics_uow_factory(session_factory: async_sessionmaker) -> Callable[[], MetricsUoW]:
    return partial(SqlMetricsUoW, session_factory)
