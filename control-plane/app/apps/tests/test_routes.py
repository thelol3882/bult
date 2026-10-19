"""PUT /apps/{name}/routes: validation and ownership of the target."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.apps.repositories.apps import AppRoute
from app.apps.uow import InMemoryAppsUoW

REPO = "https://github.com/example/repo.git"


def create(client: TestClient, name: str) -> None:
    resp = client.post("/apps", json={"name": name, "preset": "static", "repo_url": REPO})
    assert resp.status_code == 201, resp.text


@pytest.fixture(autouse=True)
def shop_and_api(client: TestClient) -> None:
    create(client, "shop")
    create(client, "shop-api")


def put(client: TestClient, routes: object, name: str = "shop"):
    return client.put(f"/apps/{name}/routes", json=routes)


def test_new_app_has_no_routes(client: TestClient):
    assert client.get("/apps/shop").json()["routes"] == []


def test_put_replaces_the_list_and_app_out_exposes_it(client: TestClient):
    resp = put(client, [{"path": "/api", "app": "shop-api"}])

    assert resp.status_code == 200
    assert resp.json()["routes"] == [{"path": "/api", "app": "shop-api"}]
    assert client.get("/apps/shop").json()["routes"] == [{"path": "/api", "app": "shop-api"}]

    assert put(client, []).json()["routes"] == []


def test_trailing_slash_is_normalized_away(client: TestClient):
    resp = put(client, [{"path": "/api/", "app": "shop-api"}])

    assert resp.json()["routes"] == [{"path": "/api", "app": "shop-api"}]


def test_paths_equal_after_normalizing_are_duplicates(client: TestClient):
    resp = put(
        client,
        [{"path": "/api", "app": "shop-api"}, {"path": "/api/", "app": "shop-api"}],
    )

    assert resp.status_code == 422


@pytest.mark.parametrize(
    "path",
    ["/", "", "api", "/API", "/a b", "/api//v1", "/api/./v1", "/-x", "/_x", "/a?b", "/a;b", "/a{b}", "//"],
)
def test_invalid_paths_are_422(client: TestClient, path: str):
    resp = put(client, [{"path": path, "app": "shop-api"}])

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_at_most_five_routes(client: TestClient):
    five = [{"path": f"/p{i}", "app": "shop-api"} for i in range(5)]

    assert put(client, five).status_code == 200
    assert put(client, [*five, {"path": "/p5", "app": "shop-api"}]).status_code == 422


def test_unknown_field_is_422(client: TestClient):
    assert put(client, [{"path": "/api", "app": "shop-api", "x": 1}]).status_code == 422


def test_route_to_itself_is_422(client: TestClient):
    resp = put(client, [{"path": "/api", "app": "shop"}])

    assert resp.status_code == 422
    assert resp.json()["code"] == "route_to_self"


def test_missing_target_is_404(client: TestClient):
    resp = put(client, [{"path": "/api", "app": "ghost"}])

    assert resp.status_code == 404
    assert resp.json()["code"] == "app_not_found"


def test_target_of_another_owner_is_403_and_nothing_is_stored(
    client: TestClient, bob: TestClient
):
    create(bob, "bobs-api")

    resp = put(client, [{"path": "/api", "app": "bobs-api"}])

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
    assert client.get("/apps/shop").json()["routes"] == []


def test_only_the_owner_can_change_routes(bob: TestClient):
    resp = put(bob, [], name="shop")

    assert resp.status_code == 403


def test_deleting_the_target_keeps_the_other_routes(
    client: TestClient, apps_uow: InMemoryAppsUoW
):
    create(client, "shop-img")
    put(
        client,
        [{"path": "/api", "app": "shop-api"}, {"path": "/img", "app": "shop-img"}],
    )

    client.delete("/apps/shop-api")

    assert asyncio.run(apps_uow.apps.list_routes()) == {
        "shop": (AppRoute("/img", "shop-img"),)
    }
