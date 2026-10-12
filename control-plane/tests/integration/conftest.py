"""Fixtures for tests on real PostgreSQL: a separate `bult_test` database, schema from Alembic."""

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_URL = "postgresql+asyncpg://bult:bult@localhost:5432/bult_test"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_URL)


async def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_async_engine(
        parsed.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": parsed.database},
            )
            if not exists:
                # CREATE DATABASE cannot take a bind parameter; the name comes from our own URL.
                await conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    """Create the test database if missing and run the real migrations on it."""
    if make_url(test_database_url).database == "bult":
        pytest.exit("refusing to run integration tests against the `bult` database")
    try:
        asyncio.run(_ensure_database(test_database_url))
    except Exception as exc:  # unreachable server, refused auth, ...
        pytest.skip(f"PostgreSQL is not available ({exc!r}); docker compose up -d postgres")

    # migrations/env.py reads DATABASE_URL from the environment.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    finally:
        if previous is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous
    return test_database_url


async def _truncate(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE apps, deploys RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture
def database_url(migrated_database: str) -> Iterator[str]:
    """URL of a migrated database with empty tables."""
    asyncio.run(_truncate(migrated_database))
    yield migrated_database
