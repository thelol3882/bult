"""Path routes reach the ingress: PUT and DELETE of apps re-apply the generated routes."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.apps.uow import InMemoryAppsUoW
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import FakeRoutes, add_running_deploy

REPO = "https://github.com/example/repo.git"


@pytest.fixture(autouse=True)
def shop_and_api(client: TestClient) -> None:
    for name in ("shop", "shop-api"):
        resp = client.post("/apps", json={"name": name, "preset": "static", "repo_url": REPO})
        assert resp.status_code == 201, resp.text


def put(client: TestClient, routes: object, name: str = "shop"):
    return client.put(f"/apps/{name}/routes", json=routes)


def test_put_reapplies_the_ingress_with_the_path_routes(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    asyncio.run(add_running_deploy(deploys_uow, "d-shop", "shop", [("node-a", 30001)]))
    asyncio.run(add_running_deploy(deploys_uow, "d-api", "shop-api", [("node-a", 30002)]))

    put(client, [{"path": "/api", "app": "shop-api"}])

    by_name = {r.name: r for r in routes.applied[-1]}
    assert [(p.path, p.target) for p in by_name["shop"].paths] == [("/api", "shop-api")]
    assert by_name["shop-api"].paths == ()
    conf = (routes.desired_dir / str(routes.last_gen) / "shop.conf").read_text()
    assert "location /api/ {" in conf


def test_stopped_target_gets_the_503_location(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    asyncio.run(add_running_deploy(deploys_uow, "d-shop", "shop", [("node-a", 30001)]))

    put(client, [{"path": "/api", "app": "shop-api"}])

    conf = (routes.desired_dir / str(routes.last_gen) / "shop.conf").read_text()
    assert "backend_unavailable" in conf
    assert "proxy_pass http://app_shop-api" not in conf


def test_deleting_the_target_drops_the_route_and_reapplies(
    client: TestClient,
    apps_uow: InMemoryAppsUoW,
    deploys_uow: InMemoryDeploysUoW,
    routes: FakeRoutes,
):
    asyncio.run(add_running_deploy(deploys_uow, "d-shop", "shop", [("node-a", 30001)]))
    asyncio.run(add_running_deploy(deploys_uow, "d-api", "shop-api", [("node-a", 30002)]))
    put(client, [{"path": "/api", "app": "shop-api"}])

    assert client.delete("/apps/shop-api").status_code == 204

    assert client.get("/apps/shop").json()["routes"] == []
    assert asyncio.run(apps_uow.apps.list_routes()) == {}
    assert [r.name for r in routes.applied[-1]] == ["shop"]
    assert routes.applied[-1][0].paths == ()
