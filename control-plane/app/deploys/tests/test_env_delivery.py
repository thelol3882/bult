"""Env variables reach the replica (platform variables win) and never reach the logs."""

import asyncio

import grpc
import pytest
from fastapi.testclient import TestClient

from app.apps.public import build_apps_facade
from app.apps.uow import InMemoryAppsUoW
from app.core.config import Settings
from app.core.events import EventBus
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import (
    FakeAgentClients,
    FakeRoutes,
    make_worker,
    rpc_error,
    run_deploys,
)

BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}
SECRET = "hunter2-do-not-leak"


@pytest.fixture(autouse=True)
def blog(client: TestClient) -> None:
    assert client.post("/apps", json=BODY).status_code == 201


def _deploy_with_worker(
    client: TestClient,
    settings: Settings,
    apps_uow: InMemoryAppsUoW,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
) -> None:
    """Queue a deploy through the API and run a worker that reads apps through the real facade."""
    assert client.post("/apps/blog/deploys").status_code == 202
    agents.build_states = ["SUCCEEDED"]
    facade = build_apps_facade(lambda: apps_uow, settings, EventBus().collector())
    asyncio.run(run_deploys(make_worker(deploys_uow, agents, routes, apps=facade)))  # pyright: ignore[reportArgumentType]


def test_env_reaches_the_replica_and_platform_variables_win(
    client: TestClient,
    settings: Settings,
    apps_uow: InMemoryAppsUoW,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    client.put("/apps/blog/env", json={"env": {"DB_URL": SECRET, "LOG_LEVEL": "debug"}})
    # The API refuses PORT, but a stored map could still hold it (an older version, manual edit).
    asyncio.run(apps_uow.apps.update("blog", env={"DB_URL": SECRET, "PORT": "1", "FORWARDED_ALLOW_IPS": "*"}))

    _deploy_with_worker(client, settings, apps_uow, deploys_uow, agents, routes)

    [call] = agents.run_calls
    assert call["env"] == {
        "DB_URL": SECRET,
        "PORT": "8000",
        "FORWARDED_ALLOW_IPS": "10.0.0.1",
    }


@pytest.mark.parametrize("run_error", [None, rpc_error(grpc.StatusCode.UNAVAILABLE, "refused")])
def test_values_never_reach_the_logs(
    client: TestClient,
    settings: Settings,
    apps_uow: InMemoryAppsUoW,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    caplog: pytest.LogCaptureFixture,
    run_error: grpc.aio.AioRpcError | None,
):
    client.put("/apps/blog/env", json={"env": {"DB_URL": SECRET}})
    client.put("/apps/blog/env", json={"env": {"BAD key": SECRET}})
    agents.run_error = run_error

    with caplog.at_level("DEBUG"):
        _deploy_with_worker(client, settings, apps_uow, deploys_uow, agents, routes)

    assert SECRET in agents.run_calls[0]["env"].values()  # the value did reach the node...
    assert SECRET not in caplog.text  # ...and nothing else
