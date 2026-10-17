"""PUT /apps/{name}/env: validation and write-only values."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.apps.uow import InMemoryAppsUoW

BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}
SECRET = "hunter2-do-not-leak"


@pytest.fixture(autouse=True)
def blog(client: TestClient) -> None:
    assert client.post("/apps", json=BODY).status_code == 201


def test_new_app_has_no_variables(client: TestClient):
    body = client.get("/apps/blog").json()

    assert body["env_keys"] == []
    assert body["replicas"] == 1


def test_put_env_returns_the_names_and_never_the_values(client: TestClient):
    resp = client.put("/apps/blog/env", json={"env": {"DB_URL": SECRET, "API_KEY": SECRET}})

    assert resp.status_code == 200
    assert resp.json()["env_keys"] == ["API_KEY", "DB_URL"]
    # Every place an app is returned, as raw text.
    assert SECRET not in resp.text
    assert SECRET not in client.get("/apps/blog").text
    assert SECRET not in client.get("/apps").text
    assert SECRET not in client.patch("/apps/blog", json={"branch": "dev"}).text
    assert SECRET not in client.get("/openapi.json").text


def test_put_env_replaces_the_whole_map(client: TestClient):
    client.put("/apps/blog/env", json={"env": {"A": "1", "B": "2"}})

    resp = client.put("/apps/blog/env", json={"env": {"C": "3"}})

    assert resp.json()["env_keys"] == ["C"]
    assert client.put("/apps/blog/env", json={"env": {}}).json()["env_keys"] == []


@pytest.mark.parametrize(
    "key",
    ["lower", "Mixed", "1STARTS_WITH_DIGIT", "HAS-DASH", "HAS SPACE", "", "PORT",
     "FORWARDED_ALLOW_IPS", "BULT_TOKEN", "BULT_", "X" * 129],
)
def test_invalid_or_reserved_keys_are_422_on_the_env_field(client: TestClient, key: str):
    resp = client.put("/apps/blog/env", json={"env": {key: SECRET}})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert "env" in body["fields"]
    assert SECRET not in resp.text
    assert client.get("/apps/blog").json()["env_keys"] == []


def test_value_limits(client: TestClient):
    too_long = "x" * 4097
    resp = client.put("/apps/blog/env", json={"env": {"BIG": too_long}})

    assert resp.status_code == 422
    assert "BIG" in resp.json()["fields"]["env"]
    assert too_long not in resp.text
    assert client.put("/apps/blog/env", json={"env": {"BIG": "x" * 4096}}).status_code == 200
    assert client.put("/apps/blog/env", json={"env": {"NUL": "a\x00b"}}).status_code == 422


def test_at_most_100_variables(client: TestClient):
    many = {f"VAR_{i}": "v" for i in range(101)}

    assert client.put("/apps/blog/env", json={"env": many}).status_code == 422
    assert client.put("/apps/blog/env", json={"env": dict(list(many.items())[:100])}).status_code == 200


@pytest.mark.parametrize("body", [{"A": "1"}, {"env": {"A": 1}}, {"env": {"A": None}}, {"env": ["A"]}])
def test_wrong_shapes_are_422(client: TestClient, body: object):
    assert client.put("/apps/blog/env", json=body).status_code == 422


def test_env_of_a_missing_app_is_404(client: TestClient):
    assert client.put("/apps/nope/env", json={"env": {}}).status_code == 404


def test_an_app_object_does_not_print_its_variables(apps_uow: InMemoryAppsUoW):
    async def scenario() -> str:
        app = await apps_uow.apps.get("blog")
        assert app is not None
        await apps_uow.apps.update("blog", env={"K": SECRET})
        app = await apps_uow.apps.get("blog")
        assert app is not None
        return repr(app)

    assert SECRET not in asyncio.run(scenario())


def test_stopped_app_names_come_from_replicas(client: TestClient, apps_uow: InMemoryAppsUoW):
    client.post("/apps", json={**BODY, "name": "shop"})
    asyncio.run(apps_uow.apps.update("shop", replicas=0))

    assert asyncio.run(apps_uow.apps.list_stopped()) == ["shop"]

