"""Deploys API tests: a fake AgentClients instead of the network."""

import asyncio
from contextlib import ExitStack

import grpc
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_agents
from app.main import create_app
from app.services.agent_client import DeployResult, ReplicaResult
from app.services.deploy_runner import MAX_POLL_FAILURES, run_deploy
from app.services.deploys import Deploy, DeployStore

COMMIT_SHA = "0123abc"
IMAGE_REPOSITORY = "registry.local/blog"
IMAGE_DIGEST = "sha256:" + "a" * 64
BUILD_ERROR = "Dockerfile: step 3/7 failed: npm ci exited with 1"
HOST_PORT = 32768
TRUSTED_PROXY = "10.0.0.1"

APP_BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


def rpc_error(code: grpc.StatusCode, details: str = "") -> grpc.aio.AioRpcError:
    """An AioRpcError as a real failed call would raise it."""
    return grpc.aio.AioRpcError(
        code, grpc.aio.Metadata(), grpc.aio.Metadata(), details=details
    )


class FakeAgentClients:
    """Same async methods as AgentClients; behaviour set in the constructor
    (like fakeBuilder in the agent's Go tests)."""

    def __init__(
        self,
        start_error: grpc.aio.AioRpcError | None = None,
        build_states: list[str] | None = None,
        run_error: grpc.aio.AioRpcError | None = None,
        start_error_times: int | None = None,
    ) -> None:
        self.start_error = start_error
        self.start_error_times = start_error_times
        self.build_states = build_states or ["RUNNING"]
        self.run_error = run_error

        self.start_calls: list[dict] = []
        self.get_calls = 0
        self.run_calls: list[dict] = []

    @property
    def runner_names(self) -> list[str]:
        return ["node-a"]

    async def start_deploy(self, deploy_id: str, **kwargs) -> DeployResult:
        self.start_calls.append({"deploy_id": deploy_id, **kwargs})
        failing = (
            self.start_error_times is None
            or len(self.start_calls) <= self.start_error_times
        )
        if self.start_error is not None and failing:
            raise self.start_error
        return DeployResult(deploy_id=deploy_id, state="RUNNING")

    async def get_deploy(self, deploy_id: str) -> DeployResult:
        item = self.build_states[min(self.get_calls, len(self.build_states) - 1)]
        self.get_calls += 1
        if isinstance(item, grpc.aio.AioRpcError):
            raise item
        state: str = item
        if state == "SUCCEEDED":
            return DeployResult(
                deploy_id=deploy_id,
                state=state,
                commit_sha=COMMIT_SHA,
                image_repository=IMAGE_REPOSITORY,
                image_digest=IMAGE_DIGEST,
            )
        if state == "FAILED":
            return DeployResult(deploy_id=deploy_id, state=state, error=BUILD_ERROR)
        return DeployResult(deploy_id=deploy_id, state=state)

    async def run_replica(self, node: str, replica_id: str, **kwargs) -> ReplicaResult:
        self.run_calls.append({"node": node, "replica_id": replica_id, **kwargs})
        if self.run_error is not None:
            raise self.run_error
        return ReplicaResult(replica_id=replica_id, node=node, host_port=HOST_PORT)

    async def close(self) -> None:
        pass


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def client_for(monkeypatch):
    """client_for(fake) -> TestClient with the fake injected and app "blog" created.

    `with TestClient(...)`: the lifespan runs (settings, deploy_tasks) and one
    event loop lives for the whole test, so run_deploy tasks are not killed
    after each request. Without `with` there would be no lifespan at all.
    """
    monkeypatch.setenv("BULT_BUILDER", "builder:50051")
    monkeypatch.setenv("BULT_RUNNERS", "node-a=runner:50051")
    monkeypatch.setenv("BULT_TRUSTED_PROXY", TRUSTED_PROXY)

    stack = ExitStack()

    def _make(agents: FakeAgentClients) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_agents] = lambda: agents
        client = stack.enter_context(TestClient(app))
        response = client.post("/apps", json=APP_BODY)
        assert response.status_code == 201, response.text
        return client

    yield _make
    stack.close()


# --- POST /apps/{name}/deploys, GET …/{deploy_id} -----------------------------


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
    deploy_id = client.post("/apps/blog/deploys").json()["id"]

    response = client.get(f"/apps/other/deploys/{deploy_id}")

    assert response.status_code == 404


def test_start_deploy_unknown_app(client_for):
    agents = FakeAgentClients()
    client = client_for(agents)

    response = client.post("/apps/nope/deploys")

    assert response.status_code == 404
    assert agents.start_calls == []


def test_start_deploy_builder_unavailable(client_for):
    agents = FakeAgentClients(start_error=rpc_error(grpc.StatusCode.UNAVAILABLE))
    client = client_for(agents)

    response = client.post("/apps/blog/deploys")

    assert response.status_code == 503


def test_start_deploy_invalid_argument_is_our_bug(client_for):
    secret = "invalid repo_url: /var/lib/bult/work/x"
    agents = FakeAgentClients(
        start_error=rpc_error(grpc.StatusCode.INVALID_ARGUMENT, secret)
    )
    client = client_for(agents)

    response = client.post("/apps/blog/deploys")

    assert response.status_code == 500
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


# --- run_deploy (background part), called directly ----------------------------


def _store_with_deploy(deploy_id: str) -> DeployStore:
    store = DeployStore()
    store.add(Deploy(id=deploy_id, app_name="blog"))
    return store


def test_run_deploy_success():
    agents = FakeAgentClients(build_states=["RUNNING", "SUCCEEDED"])
    store = _store_with_deploy("d1")

    asyncio.run(run_deploy(agents, store, "d1", "blog", TRUSTED_PROXY, poll_interval=0))

    deploy = store.get("blog", "d1")
    assert deploy.status == "running"
    assert deploy.node == "node-a"
    assert deploy.host_port == HOST_PORT
    assert deploy.commit_sha == COMMIT_SHA
    assert deploy.image == f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"
    assert deploy.error == ""

    assert agents.get_calls == 2
    [call] = agents.run_calls
    assert call["replica_id"] == "d1-r0"
    assert call["image_digest"] == IMAGE_DIGEST
    assert call["env"] == {"PORT": "8000", "FORWARDED_ALLOW_IPS": TRUSTED_PROXY}


def test_run_deploy_build_failed():
    agents = FakeAgentClients(build_states=["FAILED"])
    store = _store_with_deploy("d1")

    asyncio.run(run_deploy(agents, store, "d1", "blog", TRUSTED_PROXY, poll_interval=0))

    deploy = store.get("blog", "d1")
    assert deploy.status == "failed"
    assert deploy.error == BUILD_ERROR
    assert agents.run_calls == []


def test_run_deploy_run_replica_unavailable():
    details = "dial tcp 192.168.252.6:50051: connection refused"
    agents = FakeAgentClients(
        build_states=["SUCCEEDED"],
        run_error=rpc_error(grpc.StatusCode.UNAVAILABLE, details),
    )
    store = _store_with_deploy("d1")

    asyncio.run(run_deploy(agents, store, "d1", "blog", TRUSTED_PROXY, poll_interval=0))

    deploy = store.get("blog", "d1")
    assert deploy.status == "failed"
    assert deploy.error == "start failed: node is unreachable"
    assert "192.168" not in deploy.error


def test_run_deploy_poll_survives_transient_unavailable():
    agents = FakeAgentClients(
        build_states=["RUNNING", rpc_error(grpc.StatusCode.UNAVAILABLE), "SUCCEEDED"]
    )
    store = _store_with_deploy("d1")

    asyncio.run(run_deploy(agents, store, "d1", "blog", TRUSTED_PROXY, poll_interval=0))

    assert store.get("blog", "d1").status == "running"
    assert agents.get_calls == 3


def test_run_deploy_poll_gives_up_after_repeated_unavailable():
    agents = FakeAgentClients(build_states=[rpc_error(grpc.StatusCode.UNAVAILABLE)])
    store = _store_with_deploy("d1")

    asyncio.run(run_deploy(agents, store, "d1", "blog", TRUSTED_PROXY, poll_interval=0))

    deploy = store.get("blog", "d1")
    assert deploy.status == "failed"
    assert deploy.error == "build failed: node is unreachable"
    assert agents.get_calls == MAX_POLL_FAILURES
    assert agents.run_calls == []
