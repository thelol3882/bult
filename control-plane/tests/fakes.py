"""Fakes shared by the tests of several domains."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import grpc
from grpc.aio import AioRpcError

from app.agents.client import DeployResult, ReplicaResult
from app.ingress.routes import Route, RouteWriter

COMMIT_SHA = "0123abc"
IMAGE_REPOSITORY = "registry.local/blog"
IMAGE_DIGEST = "sha256:" + "a" * 64
BUILD_ERROR = "Dockerfile: step 3/7 failed: npm ci exited with 1"
HOST_PORT = 32768
TRUSTED_PROXY = "10.0.0.1"
DOMAIN = "bult.localhost"
RUNNERS = {"node-a": "10.0.0.5:50051"}


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
        return ReplicaResult(replica_id=replica_id, node=node, host_port=HOST_PORT)

    async def remove_replica(self, node: str, replica_id: str) -> None:
        self.remove_calls.append({"node": node, "replica_id": replica_id})
        if self.remove_error is not None:
            raise self.remove_error

    async def close(self) -> None:
        pass
