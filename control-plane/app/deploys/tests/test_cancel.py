"""Cancelling a deploy: queued is written directly, building goes through the builder."""

import asyncio
from datetime import UTC, datetime, timedelta

import grpc
import pytest
from fastapi.testclient import TestClient

from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import FakeAgentClients, FakeRoutes, make_worker, rpc_error, run_deploys

BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


@pytest.fixture(autouse=True)
def blog(client: TestClient) -> None:
    assert client.post("/apps", json=BODY).status_code == 201


def _add(uow: InMemoryDeploysUoW, deploy: Deploy) -> None:
    asyncio.run(uow.deploys.add(deploy))


def _get(uow: InMemoryDeploysUoW, deploy_id: str) -> Deploy:
    deploy = asyncio.run(uow.deploys.get(deploy_id))
    assert deploy is not None
    return deploy


def test_cancel_queued_deploy_needs_no_agent_call(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    deploy_id = client.post("/apps/blog/deploys").json()["id"]

    resp = client.post(f"/apps/blog/deploys/{deploy_id}/cancel")

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "cancelled"
    assert agents.cancel_calls == []
    assert _get(deploys_uow, deploy_id).lease_owner == ""
    # a cancelled deploy is not active: the next one is accepted
    assert client.post("/apps/blog/deploys").status_code == 202


def test_cancelled_queued_deploy_is_never_claimed(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    deploy_id = client.post("/apps/blog/deploys").json()["id"]
    client.post(f"/apps/blog/deploys/{deploy_id}/cancel")

    asyncio.run(run_deploys(make_worker(deploys_uow, agents, routes)))

    assert agents.start_calls == []
    assert _get(deploys_uow, deploy_id).status == "cancelled"


def test_cancel_building_asks_the_builder_and_the_worker_writes_cancelled(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="building"))

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 202, resp.text
    assert agents.cancel_calls == ["d1"]
    assert _get(deploys_uow, "d1").status == "building"  # the worker writes the end

    asyncio.run(run_deploys(make_worker(deploys_uow, agents, routes)))

    final = _get(deploys_uow, "d1")
    assert final.status == "cancelled"
    assert final.error == ""
    assert final.lease_owner == "" and final.lease_until is None
    assert agents.run_calls == []


def test_worker_takes_the_deploy_between_the_read_and_the_write(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog"))
    repo = deploys_uow.deploys
    original = repo.cancel_queued

    async def worker_wins(deploy_id: str, now: datetime) -> Deploy | None:
        _ = await repo.update(deploy_id, status="building")  # the worker got there first
        return await original(deploy_id, now)

    repo.cancel_queued = worker_wins  # pyright: ignore[reportAttributeAccessIssue]

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 202, resp.text
    assert agents.cancel_calls == ["d1"]  # fell through to the building path
    assert _get(deploys_uow, "d1").status == "building"


def test_claimed_but_not_yet_building_is_not_cancelled_in_place(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog"))
    asyncio.run(
        deploys_uow.deploys.claim("w1", timedelta(seconds=30), datetime.now(UTC))
    )
    agents.cancel_error = rpc_error(grpc.StatusCode.NOT_FOUND)  # builder: never heard of it

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_not_cancellable"
    assert _get(deploys_uow, "d1").status == "queued"  # the worker's lease is untouched


def test_cancel_starting_is_409(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="starting"))

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_not_cancellable"
    assert "starting" in resp.json()["detail"]
    assert agents.cancel_calls == []
    assert _get(deploys_uow, "d1").status == "starting"


@pytest.mark.parametrize("status", ["running", "failed", "cancelled", "superseded", "stopped"])
def test_cancel_of_a_finished_deploy_is_409(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    status: str,
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status=status))  # pyright: ignore[reportArgumentType]

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_not_cancellable"
    assert agents.cancel_calls == []
    assert _get(deploys_uow, "d1").status == status


def test_cancel_when_the_build_has_just_finished_is_409(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="building"))

    async def finished(deploy_id: str):
        from app.agents.client import DeployResult

        return DeployResult(deploy_id=deploy_id, state="SUCCEEDED")

    agents.cancel_deploy = finished  # pyright: ignore[reportAttributeAccessIssue]

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_not_cancellable"


def test_cancel_with_the_builder_down_is_503(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="building"))
    agents.cancel_error = rpc_error(grpc.StatusCode.UNAVAILABLE)

    resp = client.post("/apps/blog/deploys/d1/cancel")

    assert resp.status_code == 503
    assert resp.json()["code"] == "builder_unavailable"


def test_cancel_unknown_deploy_is_404(client: TestClient):
    resp = client.post("/apps/blog/deploys/nope/cancel")

    assert resp.status_code == 404
    assert resp.json()["code"] == "deploy_not_found"
