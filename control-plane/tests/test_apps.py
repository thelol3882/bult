"""Apps API tests. Each test gets a fresh app and a fresh store (conftest.py)."""

import pytest
from fastapi.testclient import TestClient

VALID = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/thelol3882/bult",
    "branch": "main",
    "subdir": "examples/fastapi-hello",
}


def create(client: TestClient, **overrides):
    """POST /apps with VALID, optionally changing some fields."""
    return client.post("/apps", json={**VALID, **overrides})


def test_healthz(client: TestClient):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_app(client: TestClient):
    resp = create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "blog"
    assert body["url"] == "https://blog.bult.localhost"  # computed_field made it into the response
    assert "created_at" in body

    resp = client.get("/apps/blog")
    assert resp.status_code == 200
    assert resp.json()["name"] == "blog"


def test_create_duplicate_name(client: TestClient):
    assert create(client).status_code == 201
    resp = create(client)
    assert resp.status_code == 409  # state check: the store, not Pydantic


@pytest.mark.parametrize("name", ["-blog", "blog-", "Blog", "b" * 64, "", "api", "my_app"])
def test_create_invalid_name(client: TestClient, name: str):
    resp = create(client, name=name)
    assert resp.status_code == 422  # shape check: Pydantic, before the handler runs
    # every error points at the name field of the body
    assert any(err["loc"] == ["body", "name"] for err in resp.json()["detail"])


def test_create_rejects_non_https_repo(client: TestClient):
    resp = create(client, repo_url="http://github.com/thelol3882/bult")
    assert resp.status_code == 422


def test_list_is_sorted(client: TestClient):
    for name in ("zeta", "alpha", "mid"):
        assert create(client, name=name).status_code == 201
    names = [app["name"] for app in client.get("/apps").json()]
    assert names == ["alpha", "mid", "zeta"]


def test_get_missing(client: TestClient):
    assert client.get("/apps/nope").status_code == 404


def test_delete(client: TestClient):
    assert create(client).status_code == 201
    resp = client.delete("/apps/blog")
    assert resp.status_code == 204
    assert resp.content == b""  # 204 must have no body
    assert client.get("/apps/blog").status_code == 404
    assert client.delete("/apps/blog").status_code == 404
