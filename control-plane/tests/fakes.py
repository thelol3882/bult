"""Fakes shared by the tests of several domains."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import grpc
from fastapi.testclient import TestClient
from grpc.aio import AioRpcError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.agents.client import DeployResult, ReplicaInfo, ReplicaResult
from app.auth.services.passwords import PasswordHasher
from app.ingress.routes import Route, RouteWriter

COMMIT_SHA = "0123abc"
IMAGE_REPOSITORY = "registry.local/blog"
IMAGE_DIGEST = "sha256:" + "a" * 64
BUILD_ERROR = "Dockerfile: step 3/7 failed: npm ci exited with 1"
HOST_PORT = 32768
TRUSTED_PROXY = "10.0.0.1"
DOMAIN = "bult.localhost"
RUNNERS = {"node-a": "10.0.0.5:50051"}
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


def rpc_error(code: grpc.StatusCode, details: str = "") -> AioRpcError:
    """An AioRpcError as a failed call raises it."""
    return AioRpcError(code, grpc.aio.Metadata(), grpc.aio.Metadata(), details=details)


class FakeRoutes(RouteWriter):
    """A real RouteWriter whose "sidecar" accepts every version at once."""

    def __init__(self, base_dir: Path, domain: str) -> None:
        super().__init__(base_dir, domain)
        self.applied: list[list[Route]] = []

    def apply(self, routes: list[Route]) -> int:
        self.applied.append(list(routes))
        return super().apply(routes)

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
    ) -> None:
        self.start_error = start_error
        self.start_error_times = start_error_times
        self.build_states = build_states or ["RUNNING"]
        self.run_error = run_error
        self.remove_error = remove_error
        self.on_run = on_run  # runs after a successful RunReplica

        self.start_calls: list[dict[str, Any]] = []
        self.get_calls = 0
        self.run_calls: list[dict[str, Any]] = []
        self.remove_calls: list[dict[str, Any]] = []
        self.list_error: AioRpcError | None = None
        # What the "nodes" run: node -> replica_id -> replica.
        self.replicas: dict[str, dict[str, ReplicaInfo]] = {}

    def seed_replica(
        self, replica_id: str, app_id: str, node: str = "node-a", port: int = HOST_PORT
    ) -> None:
        """A replica already running on a node (as if left by an earlier deploy)."""
        self.replicas.setdefault(node, {})[replica_id] = ReplicaInfo(
            replica_id, app_id, port, "RUNNING"
        )

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
        if self.run_error is not None:
            raise self.run_error
        if self.on_run is not None:
            await self.on_run()
        self.seed_replica(replica_id, kwargs["app_id"], node, HOST_PORT)
        return ReplicaResult(replica_id=replica_id, node=node, host_port=HOST_PORT)

    async def remove_replica(self, node: str, replica_id: str) -> None:
        self.remove_calls.append({"node": node, "replica_id": replica_id})
        if self.remove_error is not None:
            raise self.remove_error
        self.replicas.get(node, {}).pop(replica_id, None)

    async def list_replicas(self, node: str) -> list[ReplicaInfo]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.replicas.get(node, {}).values())

    async def close(self) -> None:
        pass
