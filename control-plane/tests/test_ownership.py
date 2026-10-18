"""Apps belong to their creator: another user gets 403, anonymous gets 401."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import FakeAgentClients

APP_BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


@pytest.fixture
def blog(client: TestClient, deploys_uow: InMemoryDeploysUoW) -> None:
    """alice's app "blog" with one deploy "d1"."""
    assert client.post("/apps", json=APP_BODY).status_code == 201
    asyncio.run(deploys_uow.deploys.add(Deploy(id="d1", app_name="blog")))


@pytest.mark.usefixtures("blog")
@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/apps/blog", None),
        ("PATCH", "/apps/blog", {"branch": "dev"}),
        ("DELETE", "/apps/blog", None),
        ("POST", "/apps/blog/deploys", None),
        ("GET", "/apps/blog/deploys", None),
        ("GET", "/apps/blog/deploys/d1", None),
        ("POST", "/apps/blog/deploys/d1/rollback", None),
        ("POST", "/apps/blog/deploys/d1/cancel", None),
        ("POST", "/apps/blog/stop", None),
        ("POST", "/apps/blog/start", None),
        ("PUT", "/apps/blog/env", {"env": {"A": "1"}}),
        ("PUT", "/apps/blog/replicas", {"replicas": 2}),
        ("GET", "/apps/blog/logs", None),
    ],
)
def test_other_user_gets_403(bob: TestClient, method: str, path: str, body: dict | None):
    resp = bob.request(method, path, json=body)

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


@pytest.mark.usefixtures("blog")
def test_forbidden_requests_change_nothing(
    client: TestClient, bob: TestClient, agents: FakeAgentClients
):
    bob.patch("/apps/blog", json={"branch": "dev"})
    bob.delete("/apps/blog")
    bob.post("/apps/blog/deploys")
    bob.post("/apps/blog/stop")
    bob.post("/apps/blog/deploys/d1/cancel")
    bob.put("/apps/blog/env", json={"env": {"A": "1"}})

    app = client.get("/apps/blog").json()
    assert app["branch"] == "main"
    assert (app["replicas"], app["env_keys"]) == (1, [])
    assert agents.start_calls == []
    assert agents.remove_calls == []


@pytest.mark.usefixtures("blog")
def test_owner_still_has_access(client: TestClient):
    assert client.get("/apps/blog").status_code == 200
    assert client.get("/apps/blog/deploys/d1").status_code == 200


def test_list_shows_only_own_apps(client: TestClient, bob: TestClient):
    for name in ("a1", "a2", "a3"):
        client.post("/apps", json={**APP_BODY, "name": name})
    bob.post("/apps", json={**APP_BODY, "name": "b1"})

    mine = client.get("/apps").json()
    theirs = bob.get("/apps").json()

    assert mine["count"] == 3
    assert [a["name"] for a in mine["results"]] == ["a1", "a2", "a3"]
    assert theirs["count"] == 1
    assert [a["name"] for a in theirs["results"]] == ["b1"]


def test_app_name_taken_across_users(client: TestClient, bob: TestClient):
    client.post("/apps", json=APP_BODY)

    resp = bob.post("/apps", json=APP_BODY)

    assert resp.status_code == 409
    assert resp.json()["code"] == "app_name_taken"


@pytest.mark.usefixtures("blog")
@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/apps"),
        ("POST", "/apps"),
        ("GET", "/apps/blog"),
        ("PATCH", "/apps/blog"),
        ("DELETE", "/apps/blog"),
        ("POST", "/apps/blog/deploys"),
        ("GET", "/apps/blog/deploys"),
        ("GET", "/apps/blog/deploys/d1"),
        ("POST", "/apps/blog/deploys/d1/rollback"),
        ("POST", "/apps/blog/stop"),
        ("POST", "/apps/blog/start"),
        ("PUT", "/apps/blog/env"),
        ("GET", "/apps/blog/logs"),
    ],
)
def test_no_token_is_401(anon_client: TestClient, method: str, path: str):
    resp = anon_client.request(method, path)

    assert resp.status_code == 401
    assert resp.json()["code"] == "not_authenticated"


def test_healthz_is_public(anon_client: TestClient):
    assert anon_client.get("/healthz").status_code == 200
