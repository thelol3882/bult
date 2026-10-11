"""Endpoints outside a single domain: health and DELETE /apps/{name}."""

from fastapi.testclient import TestClient

APP_BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/thelol3882/bult",
}


def test_healthz(client: TestClient):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_delete(client: TestClient):
    assert client.post("/apps", json=APP_BODY).status_code == 201
    resp = client.delete("/apps/blog")
    assert resp.status_code == 204
    assert resp.content == b""  # 204 must have no body
    assert client.get("/apps/blog").status_code == 404
    assert client.delete("/apps/blog").status_code == 404
