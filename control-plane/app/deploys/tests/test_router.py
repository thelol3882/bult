"""Deploys API tests: a fake AgentClients instead of the network."""

import asyncio
from contextlib import ExitStack

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import get_agents
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import FakeAgentClients, auth_headers

APP_BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


@pytest.fixture
def client_for(app: FastAPI):
    """client_for(fake) -> client with the fake injected and app "blog" created.

    Uses `with TestClient`: one event loop for the whole test, one portal for every request.
    """
    stack = ExitStack()

    def _make(agents: FakeAgentClients) -> TestClient:
        app.dependency_overrides[get_agents] = lambda: agents
        client = stack.enter_context(TestClient(app))
        client.headers.update(auth_headers(client, "alice@example.com"))
        response = client.post("/apps", json=APP_BODY)
        assert response.status_code == 201, response.text
        return client

    yield _make
    stack.close()


def test_start_deploy_accepted(client_for):
    client = client_for(FakeAgentClients())

    response = client.post("/apps/blog/deploys")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"]
    assert body["app_name"] == "blog"
    assert body["status"] == "queued"

    got = client.get(f"/apps/blog/deploys/{body['id']}")
    assert got.status_code == 200
    assert got.json() == body


def test_get_deploy_of_another_app_is_404(client_for):
    client = client_for(FakeAgentClients())
    client.post("/apps", json={**APP_BODY, "name": "other"})
    deploy_id = client.post("/apps/blog/deploys").json()["id"]

    response = client.get(f"/apps/other/deploys/{deploy_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "deploy_not_found"


def test_start_deploy_unknown_app(client_for):
    agents = FakeAgentClients()
    client = client_for(agents)

    response = client.post("/apps/nope/deploys")

    assert response.status_code == 404
    assert response.json()["code"] == "app_not_found"
    assert agents.start_calls == []


def test_second_deploy_while_one_is_active_is_409(client_for):
    agents = FakeAgentClients()
    client = client_for(agents)

    first = client.post("/apps/blog/deploys")
    second = client.post("/apps/blog/deploys")

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["code"] == "deploy_in_progress"
    history = client.get("/apps/blog/deploys").json()["results"]
    assert [d["id"] for d in history] == [first.json()["id"]]


def test_start_deploy_makes_no_agent_call(client_for):
    agents = FakeAgentClients()
    client = client_for(agents)

    assert client.post("/apps/blog/deploys").status_code == 202

    assert agents.start_calls == []  # the worker calls the builder, not the request


def test_new_deploy_is_allowed_once_the_previous_one_finished(
    client_for, deploys_uow: InMemoryDeploysUoW
):
    client = client_for(FakeAgentClients())
    first = client.post("/apps/blog/deploys").json()["id"]
    asyncio.run(deploys_uow.deploys.update(first, status="running"))

    assert client.post("/apps/blog/deploys").status_code == 202
