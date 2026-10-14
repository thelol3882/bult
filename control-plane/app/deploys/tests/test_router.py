"""Deploys API tests: a fake AgentClients instead of the network."""

from contextlib import ExitStack

import grpc
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import get_agents
from tests.fakes import FakeAgentClients, auth_headers, rpc_error

APP_BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


@pytest.fixture
def client_for(app: FastAPI):
    """client_for(fake) -> client with the fake injected and app "blog" created.

    Uses `with TestClient`: one event loop for the whole test, so run_deploy tasks survive requests.
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
    assert body["status"] == "building"

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


def test_start_deploy_builder_unavailable(client_for):
    agents = FakeAgentClients(start_error=rpc_error(grpc.StatusCode.UNAVAILABLE))
    client = client_for(agents)

    response = client.post("/apps/blog/deploys")

    assert response.status_code == 503
    assert response.json()["code"] == "builder_unavailable"


def test_start_deploy_invalid_argument_is_our_bug(client_for):
    secret = "invalid repo_url: /var/lib/bult/work/x"
    agents = FakeAgentClients(
        start_error=rpc_error(grpc.StatusCode.INVALID_ARGUMENT, secret)
    )
    client = client_for(agents)

    response = client.post("/apps/blog/deploys")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert secret not in response.text
    assert "/var/lib" not in response.text


def test_start_deploy_deadline_retries_same_id(client_for):
    agents = FakeAgentClients(
        start_error=rpc_error(grpc.StatusCode.DEADLINE_EXCEEDED),
        start_error_times=1,
    )
    client = client_for(agents)

    response = client.post("/apps/blog/deploys")

    assert response.status_code == 202, response.text
    assert len(agents.start_calls) == 2
    first, second = (call["deploy_id"] for call in agents.start_calls)
    assert first == second == response.json()["id"]
