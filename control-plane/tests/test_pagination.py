"""Cursor helpers and the deploy history endpoint."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW

APP = {"name": "blog", "preset": "fastapi", "repo_url": "https://github.com/x/y"}


def test_cursor_roundtrip():
    created_at = datetime(2026, 10, 13, 10, 0, 0, 123456, tzinfo=UTC)
    assert decode_cursor(encode_cursor(created_at, "d1")) == (created_at, "d1")


@pytest.mark.parametrize("cursor", ["not-base64!", "Zm9v", ""])
def test_decode_rejects_garbage(cursor: str):
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


def test_bad_cursor_is_422(client: TestClient):
    client.post("/apps", json=APP)
    resp = client.get("/apps/blog/deploys?cursor=not-base64!")
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_cursor"


def test_empty_history(client: TestClient):
    client.post("/apps", json=APP)
    assert client.get("/apps/blog/deploys").json() == {"results": [], "next_cursor": None}


def test_history_walks_pages_newest_first(client: TestClient, deploys_uow: InMemoryDeploysUoW):
    client.post("/apps", json=APP)
    import asyncio

    async def seed() -> None:
        for deploy_id in ("d1", "d2", "d3"):
            await deploys_uow.deploys.add(Deploy(id=deploy_id, app_name="blog"))

    asyncio.run(seed())

    first = client.get("/apps/blog/deploys?limit=2").json()
    assert [d["id"] for d in first["results"]] == ["d3", "d2"]
    second = client.get(f"/apps/blog/deploys?limit=2&cursor={first['next_cursor']}").json()
    assert [d["id"] for d in second["results"]] == ["d1"]
    assert second["next_cursor"] is None
