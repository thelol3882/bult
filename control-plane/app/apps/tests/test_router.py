"""Apps API tests."""

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
    """POST /apps with VALID plus overrides."""
    return client.post("/apps", json={**VALID, **overrides})


def test_create_app(client: TestClient):
    resp = create(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "blog"
    assert body["url"] == "http://blog.bult.localhost"
    assert "created_at" in body

    resp = client.get("/apps/blog")
    assert resp.status_code == 200
    assert resp.json()["name"] == "blog"


def test_create_duplicate_name(client: TestClient):
    assert create(client).status_code == 201
    resp = create(client)
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "app_name_taken"
    assert body["field"] == "name"


@pytest.mark.parametrize("name", ["-blog", "blog-", "Blog", "b" * 64, "", "api", "my_app"])
def test_create_invalid_name(client: TestClient, name: str):
    resp = create(client, name=name)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert "name" in body["fields"]


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
