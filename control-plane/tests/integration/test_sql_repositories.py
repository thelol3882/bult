"""Integration tests on real PostgreSQL (docker compose up -d postgres)."""

import asyncio
import functools
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.apps.errors import AppNameTakenError
from app.apps.repositories.apps import App
from app.apps.uow import SqlAppsUoW
from app.core.db import create_engine, create_session_factory
from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import SqlDeploysUoW

pytestmark = pytest.mark.integration


def db_test(
    test: Callable[[async_sessionmaker], Coroutine[Any, Any, None]],
) -> Callable[[str], None]:
    """Run an async test in its own loop (no pytest-asyncio) on a migrated, empty DB."""

    @functools.wraps(test)
    def wrapper(database_url: str) -> None:
        async def main() -> None:
            engine = create_engine(database_url)
            try:
                await test(create_session_factory(engine))
            finally:
                await engine.dispose()

        asyncio.run(main())

    del wrapper.__wrapped__  # pytest must see `database_url`, not `factory`
    return wrapper


def make_app(name: str = "hello") -> App:
    return App(
        name=name,
        preset="fastapi",
        repo_url="https://github.com/thelol3882/bult",
        branch="main",
        subdir="examples/fastapi-html",
    )


async def read_timestamps(
    factory: async_sessionmaker, deploy_id: str
) -> tuple[datetime, datetime]:
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT created_at, updated_at FROM deploys WHERE id = :i"),
                {"i": deploy_id},
            )
        ).one()
        return row.created_at, row.updated_at


@db_test
async def test_app_repository_roundtrip(factory: async_sessionmaker):
    async with SqlAppsUoW(factory) as uow:
        added = await uow.apps.add(make_app("hello"))
        await uow.apps.add(make_app("alpha"))
        await uow.commit()

    assert isinstance(added.id, UUID)
    assert isinstance(added.created_at, datetime)

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.get("hello") == added
        assert await uow.apps.get("missing") is None
        assert [a.name for a in await uow.apps.list()] == ["alpha", "hello"]
        assert await uow.apps.delete("hello") is True
        assert await uow.apps.delete("hello") is False
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        assert [a.name for a in await uow.apps.list()] == ["alpha"]


@db_test
async def test_duplicate_name_is_app_name_taken(factory: async_sessionmaker):
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app())
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        with pytest.raises(AppNameTakenError):
            await uow.apps.add(make_app())


@db_test
async def test_deleting_app_cascades_to_deploys(factory: async_sessionmaker):
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app())
        await uow.commit()
    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.add(Deploy(id="d1", app_name="hello"))
        await uow.commit()

    # Only the apps repository is touched: the rows go away through the FK.
    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.delete("hello") is True
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.list_all() == []


@db_test
async def test_uow_without_commit_saves_nothing(factory: async_sessionmaker):
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app())

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.list() == []


@db_test
async def test_update_missing_deploy_returns_none(factory: async_sessionmaker):
    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.update("nope", status="running") is None


@db_test
async def test_update_bumps_updated_at_but_not_created_at(
    factory: async_sessionmaker,
):
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app())
        await uow.commit()
    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.add(Deploy(id="d1", app_name="hello"))
        await uow.commit()
    created, updated = await read_timestamps(factory, "d1")

    async with SqlDeploysUoW(factory) as uow:
        changed = await uow.deploys.update("d1", status="running", host_port=8080)
        await uow.commit()
    assert changed is not None
    assert changed.status == "running"
    assert changed.host_port == 8080

    created_after, updated_after = await read_timestamps(factory, "d1")
    assert created_after == created
    assert updated_after > updated


def test_cursor_pages_with_equal_created_at_have_no_gaps_or_duplicates():
    # Insert 5 deploys for one app, several with the SAME created_at (set it explicitly),
    # walk list_for_app with limit=2 following the cursor until it ends →
    # every deploy id appears exactly once, newest first.
    raise NotImplementedError
