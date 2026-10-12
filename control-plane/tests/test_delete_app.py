"""DELETE /apps/{name}: the AppDeleted handler cleans up before the 204."""

import asyncio

import grpc
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apps.events import AppDeleted
from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route
from tests.fakes import FakeAgentClients, FakeRoutes, rpc_error

BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/thelol3882/bult",
}


def _running(deploy_id: str, app_name: str, port: int) -> Deploy:
    return Deploy(
        id=deploy_id, app_name=app_name, status="running", node="node-a", host_port=port
    )


def _create(client: TestClient, name: str) -> None:
    assert client.post("/apps", json={**BODY, "name": name}).status_code == 201


def test_delete_cleans_up_deploys_replicas_and_routes(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _create(client, "blog")
    _create(client, "shop")
    asyncio.run(deploys_uow.deploys.add(_running("d-blog", "blog", 30001)))
    asyncio.run(deploys_uow.deploys.add(_running("d-shop", "shop", 30002)))

    resp = client.delete("/apps/blog")

    assert resp.status_code == 204
    assert asyncio.run(deploys_uow.deploys.get("d-blog")) is None
    assert asyncio.run(deploys_uow.deploys.get("d-shop")) is not None
    assert agents.remove_calls == [{"node": "node-a", "replica_id": "d-blog-r0"}]
    assert routes.applied[-1] == [Route("shop", "10.0.0.5", 30002)]
    assert client.get("/apps/blog").status_code == 404


def test_delete_unknown_app_changes_nothing(
    client: TestClient, agents: FakeAgentClients, routes: FakeRoutes
):
    assert client.delete("/apps/nope").status_code == 404
    assert routes.applied == []
    assert agents.remove_calls == []


def test_failed_replica_removal_is_logged_not_raised(
    app: FastAPI,
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    caplog: pytest.LogCaptureFixture,
):
    agents.remove_error = rpc_error(grpc.StatusCode.UNAVAILABLE)
    _create(client, "blog")
    asyncio.run(deploys_uow.deploys.add(_running("d-blog", "blog", 30001)))

    assert client.delete("/apps/blog").status_code == 204
    assert "could not remove replica d-blog-r0" in caplog.text


def test_handler_failure_is_an_error_response_not_204(app: FastAPI):
    async def boom(event: AppDeleted) -> None:
        raise RuntimeError("cleanup exploded")

    app.state.event_bus.subscribe(AppDeleted, boom)
    client = TestClient(app, raise_server_exceptions=False)
    _create(client, "blog")

    resp = client.delete("/apps/blog")

    assert resp.status_code == 500
    assert resp.json()["code"] == "internal_error"
