"""Fakes shared by the tests of several domains."""

from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import grpc
from fastapi.testclient import TestClient
from grpc.aio import AioRpcError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.agents.client import DeployResult, ReplicaInfo, ReplicaResult
from app.apps.services.facade import App, AppNotFoundError, AppRoute, AppsFacade
from app.auth.services.passwords import PasswordHasher
from app.deploys.repositories.deploys import Deploy, DeployStatus
from app.deploys.repositories.replicas import Replica, replica_id
from app.deploys.services.worker import DeployWorker
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route, RouteWriter, Upstream
from app.nodes.services.facade import NodesFacade
from app.nodes.services.nodes import RunnerNode

COMMIT_SHA = "0123abc"
IMAGE_REPOSITORY = "registry.local/blog"
IMAGE_DIGEST = "sha256:" + "a" * 64
BUILD_ERROR = "Dockerfile: step 3/7 failed: npm ci exited with 1"
HOST_PORT = 32768
TRUSTED_PROXY = "10.0.0.1"
DOMAIN = "bult.localhost"
RUNNERS = {"node-a": "10.0.0.5:50051"}
NODE_B = ("node-b", "10.0.0.6:50051")
NODE_TOKENS = {
    "node-a": "a" * 40,
    "node-b": "b" * 40,
    "builder-1": "c" * 40,
}
PASSWORD = "correct horse battery"
TEST_JWT_SECRET = "test-secret-" + "x" * 32


class CheapPasswordHasher(PasswordHasher):
    """The production PasswordHasher with cheap argon2 parameters (m=64, t=2)."""

    def __init__(self) -> None:
        self._hasher = PasswordHash(
            (Argon2Hasher(time_cost=2, memory_cost=64, parallelism=1),)
        )
        self._dummy_hash = self._hasher.hash("dummy")


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Register the user (if new), log in and return the Authorization header."""
    client.post("/auth/register", json={"email": email, "password": PASSWORD})
    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class FakeClock:
    """A settable clock for the nodes' silence thresholds."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def one_route(name: str, node_ip: str, port: int) -> Route:
    """A route with a single replica behind it."""
    return Route(name, (Upstream(node_ip, port),))


class FakeNodes:
    """The part of NodesFacade the deploys domain uses; readiness is set by the test."""

    def __init__(self, runners: dict[str, str] | None = None) -> None:
        self.addresses = dict(RUNNERS if runners is None else runners)
        self.not_ready: set[str] = set()

    def add(self, name: str, address: str, ready: bool = True) -> None:
        self.addresses[name] = address
        self.set_ready(name, ready)

    def set_ready(self, name: str, ready: bool) -> None:
        if ready:
            self.not_ready.discard(name)
        else:
            self.not_ready.add(name)

    async def runners(self) -> list[RunnerNode]:
        return [
            RunnerNode(name, addr, name not in self.not_ready)
            for name, addr in sorted(self.addresses.items())
        ]

    async def builder_address(self) -> str | None:
        return "builder:50051"

    async def runner_address(self, name: str) -> str | None:
        return self.addresses.get(name)

    async def runner_names(self) -> list[str]:
        return sorted(self.addresses)


def rpc_error(code: grpc.StatusCode, details: str = "") -> AioRpcError:
    """An AioRpcError as a failed call raises it."""
    return AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), details=details)


class FakeRoutes(RouteWriter):
    """A real RouteWriter whose "sidecar" accepts every version at once."""

    def __init__(self, base_dir: Path, domain: str) -> None:
        super().__init__(base_dir, domain)
        self.applied: list[list[Route]] = []
        self.applied_stopped: list[list[str]] = []

    def apply(self, routes: list[Route], stopped: Iterable[str] = ()) -> int:
        stopped = list(stopped)
        self.applied.append(list(routes))
        self.applied_stopped.append(stopped)
        return super().apply(routes, stopped)

    async def wait_applied(self, generation: int, timeout: float = 10.0) -> None:
        return None


class FakeAgentClients:
    """Same async methods as AgentClients; behaviour set in the constructor."""

    def __init__(
        self,
        start_error: AioRpcError | None = None,
        build_states: list[str | AioRpcError] | None = None,
        run_error: AioRpcError | None = None,
        remove_error: AioRpcError | None = None,
        on_run: Callable[[], Awaitable[None]] | None = None,
        start_error_times: int | None = None,
        nodes: FakeNodes | None = None,
    ) -> None:
        self.nodes = nodes or FakeNodes()
        self.start_error = start_error
        self.start_error_times = start_error_times
        self.build_states: list[str | AioRpcError] = build_states or ["RUNNING"]
        self.run_error = run_error
        self.remove_error = remove_error
        self.run_errors: dict[str, AioRpcError] = {}  # RunReplica fails on these nodes only
        self.fail_replica_ids: set[str] = set()  # RunReplica fails for these replicas anywhere
        self.on_run = on_run  # runs after a successful RunReplica

        self.start_calls: list[dict[str, Any]] = []
        self.get_calls = 0
        self.cancel_calls: list[str] = []
        self.cancel_error: AioRpcError | None = None
        self.cancelled_builds: set[str] = set()  # get_deploy reports these as CANCELLED
        self.run_calls: list[dict[str, Any]] = []
        self.remove_calls: list[dict[str, Any]] = []
        self.list_error: AioRpcError | None = None
        self.log_text = ""
        self.log_error: AioRpcError | None = None
        self.log_calls: list[dict[str, Any]] = []
        # What the "nodes" run: node -> replica_id -> replica.
        self.replicas: dict[str, dict[str, ReplicaInfo]] = {}

    def seed_replica(
        self, replica_id: str, app_id: str, node: str = "node-a", port: int = HOST_PORT
    ) -> None:
        """A replica already running on a node (as if left by an earlier deploy)."""
        self.replicas.setdefault(node, {})[replica_id] = ReplicaInfo(
            replica_id, app_id, port, "RUNNING"
        )

    async def runner_names(self) -> list[str]:
        return await self.nodes.runner_names()

    async def start_deploy(self, deploy_id: str, **kwargs) -> DeployResult:
        self.start_calls.append({"deploy_id": deploy_id, **kwargs})
        failing = (
            self.start_error_times is None
            or len(self.start_calls) <= self.start_error_times
        )
        if self.start_error is not None and failing:
            raise self.start_error
        return DeployResult(deploy_id=deploy_id, state="RUNNING")

    async def cancel_deploy(self, deploy_id: str) -> DeployResult:
        self.cancel_calls.append(deploy_id)
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled_builds.add(deploy_id)
        return DeployResult(deploy_id=deploy_id, state="CANCELLED")

    async def get_deploy(self, deploy_id: str) -> DeployResult:
        if deploy_id in self.cancelled_builds:
            return DeployResult(deploy_id=deploy_id, state="CANCELLED")
        item = self.build_states[min(self.get_calls, len(self.build_states) - 1)]
        self.get_calls += 1
        if isinstance(item, AioRpcError):
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
        error = self.run_errors.get(node, self.run_error)
        if replica_id in self.fail_replica_ids:
            error = rpc_error(grpc.StatusCode.UNAVAILABLE)
        if error is not None:
            raise error
        if self.on_run is not None:
            await self.on_run()
        port = HOST_PORT + len(self.run_calls) - 1  # a distinct port per call
        self.seed_replica(replica_id, kwargs["app_id"], node, port)
        return ReplicaResult(replica_id=replica_id, node=node, host_port=port)

    async def remove_replica(self, node: str, replica_id: str) -> None:
        self.remove_calls.append({"node": node, "replica_id": replica_id})
        if self.remove_error is not None:
            raise self.remove_error
        self.replicas.get(node, {}).pop(replica_id, None)

    async def list_replicas(self, node: str) -> list[ReplicaInfo]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.replicas.get(node, {}).values())

    async def logs(self, node: str, replica_id: str, tail_lines: int) -> str:
        self.log_calls.append(
            {"node": node, "replica_id": replica_id, "tail_lines": tail_lines}
        )
        if self.log_error is not None:
            raise self.log_error
        return self.log_text

    async def close(self) -> None:
        pass


class FakeApps:
    """The part of AppsFacade the worker and the deploy service use."""

    def __init__(
        self,
        missing: bool = False,
        env: dict[str, str] | None = None,
        stopped: list[str] | None = None,
        routes: dict[str, tuple[AppRoute, ...]] | None = None,
    ) -> None:
        self.routes = routes or {}
        self.missing = missing
        self.env = env or {}
        self.stopped = stopped or []
        self.replicas_set: list[tuple[str, int]] = []

    async def get_app_unchecked(self, name: str) -> App:
        if self.missing:
            raise AppNotFoundError(name)
        return App(
            name=name,
            preset="fastapi",
            repo_url="https://github.com/example/blog.git",
            branch="main",
            subdir="",
            env=self.env,
        )

    async def path_routes(self) -> dict[str, tuple[AppRoute, ...]]:
        return dict(self.routes)

    async def stopped_app_names(self) -> list[str]:
        return list(self.stopped)


async def add_running_deploy(
    uow: InMemoryDeploysUoW,
    deploy_id: str,
    app_name: str,
    replicas: list[tuple[str, int]] | None = None,
    *,
    image: str = "registry.local/blog@sha256:old",
    status: DeployStatus = "running",
) -> Deploy:
    """A deploy that ran, with replicas at (node, host_port); default: one on node-a.

    Only a running deploy keeps live replica rows; the others have them retired.
    """
    placements = replicas if replicas is not None else [("node-a", HOST_PORT)]
    deploy = await uow.deploys.add(
        Deploy(
            id=deploy_id,
            app_name=app_name,
            status=status,
            image=image,
            ran=True,
            desired_replicas=len(placements) or 1,
        )
    )
    for index, (node, port) in enumerate(placements):
        await uow.replicas.save(
            Replica(replica_id(deploy_id, index), deploy_id, index, node, port)
        )
    if status != "running":
        await uow.replicas.mark_removed(
            replica_id(deploy_id, i) for i in range(len(placements))
        )
    return deploy


def make_worker(
    uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: RouteWriter,
    *,
    apps: FakeApps | None = None,
    nodes: FakeNodes | None = None,
    worker_id: str = "w1",
    clock: Callable[[], datetime] | None = None,
    **kwargs: Any,
) -> DeployWorker:
    """A worker on fakes that polls without sleeping (tests drive it with tick/join)."""
    options: dict[str, Any] = {
        "worker_id": worker_id,
        "poll_interval": 0.01,
        "build_poll_interval": 0,
        "renew_every": 10.0,
        **kwargs,
    }
    if clock is not None:
        options["clock"] = clock
    return DeployWorker(
        agents,
        lambda: uow,
        cast(AppsFacade, apps or FakeApps()),
        cast(NodesFacade, nodes or agents.nodes),
        routes,
        TRUSTED_PROXY,
        **options,
    )


async def run_deploys(worker: DeployWorker) -> None:
    """One claim round, then wait until everything claimed is processed."""
    await worker.tick()
    await worker.join()
