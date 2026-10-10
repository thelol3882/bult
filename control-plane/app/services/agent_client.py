"""Async gRPC client to the node agents (bultd): one channel per node.

Created once in the app lifespan, closed on shutdown, handed to routers via
Depends. protobuf messages never leave this module: callers get the
dataclasses below — routers and tests know nothing about agent_pb2.

Errors are NOT translated here: a failed call raises grpc.aio.AioRpcError
(.code(), .details()); the caller decides what it means (HTTP code, retry).
"""

from dataclasses import dataclass
from typing import Protocol

import grpc
from bult.agent.v1 import agent_pb2, agent_pb2_grpc

START_DEPLOY_TIMEOUT = 10
GET_DEPLOY_TIMEOUT = 10
RUN_REPLICA_TIMEOUT = 300  # includes pulling the image on the node

# HTTP/2 keepalive: a silently dead node becomes UNAVAILABLE instead of hanging.
CHANNEL_OPTIONS: list[tuple[str, int]] = [
    ("grpc.keepalive_time_ms", 30_000),  # ping after 30 s without activity
    ("grpc.keepalive_timeout_ms", 10_000),  # no ack in 10 s -> connection dead
    ("grpc.keepalive_permit_without_calls", 1),  # ping even with no RPC in flight
    ("grpc.http2.max_pings_without_data", 0),  # don't stop pinging on idle channels
]

_DEPLOY_STATE_PREFIX = "DEPLOY_STATE_"


@dataclass(frozen=True)
class DeployResult:
    """What the control plane needs from the agent's Deploy message."""

    deploy_id: str
    state: str  # "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" (DeployState without the prefix)
    commit_sha: str = ""
    image_repository: str = ""
    image_digest: str = ""
    error: str = ""  # user-facing text, already cleaned by the agent


@dataclass(frozen=True)
class ReplicaResult:
    """What the control plane needs from the agent's Replica message."""

    replica_id: str
    node: str
    host_port: int


class UnknownNodeError(Exception):
    """No runner with this name in the configuration."""


class AgentClients:
    """Channels and stubs to the builder and every runner node."""

    def __init__(self, builder_addr: str, runner_addrs: dict[str, str]) -> None:
        """builder_addr: "host:port"; runner_addrs: node name -> "host:port".

        Creating a channel does not connect: a node that is down does not stop
        the API from starting; the first call to it fails with UNAVAILABLE.
        """
        self._builder_channel = grpc.aio.insecure_channel(
            builder_addr, options=CHANNEL_OPTIONS
        )
        self._builder = agent_pb2_grpc.BuildServiceStub(self._builder_channel)

        self._runner_channels: dict[str, grpc.aio.Channel] = {}
        self._runners: dict[str, agent_pb2_grpc.RuntimeServiceStub] = {}
        for name, addr in runner_addrs.items():
            channel = grpc.aio.insecure_channel(addr, options=CHANNEL_OPTIONS)
            self._runner_channels[name] = channel
            self._runners[name] = agent_pb2_grpc.RuntimeServiceStub(channel)

    @property
    def runner_names(self) -> list[str]:
        """Configured runner nodes, in configuration order (used by the scheduler)."""
        return list(self._runners)

    async def start_deploy(
        self,
        deploy_id: str,
        app_id: str,
        repo_url: str,
        branch: str,
        subdir: str,
        dockerfile: str,
    ) -> DeployResult:
        """StartDeploy on the builder. Idempotent on deploy_id: safe to retry."""
        request = agent_pb2.StartDeployRequest(
            deploy_id=deploy_id,
            app_id=app_id,
            source=agent_pb2.Source(
                repo_url=repo_url,
                branch=branch,
                subdir=subdir,
            ),
            dockerfile=dockerfile,
        )
        response = await self._builder.StartDeploy(
            request, timeout=START_DEPLOY_TIMEOUT
        )
        return _deploy_result(response.deploy)

    async def get_deploy(self, deploy_id: str) -> DeployResult:
        """GetDeploy on the builder (NOT_FOUND → AioRpcError like any other code)."""
        request = agent_pb2.GetDeployRequest(deploy_id=deploy_id)
        response = await self._builder.GetDeploy(request, timeout=GET_DEPLOY_TIMEOUT)
        return _deploy_result(response.deploy)

    async def run_replica(
        self,
        node: str,
        replica_id: str,
        app_id: str,
        image_repository: str,
        image_digest: str,
        container_port: int,
        env: dict[str, str],
        cpu_millicores: int,
        memory_bytes: int,
    ) -> ReplicaResult:
        """RunReplica on one runner. Idempotent on replica_id."""
        stub = self._runners.get(node)
        if stub is None:
            raise UnknownNodeError(node)

        request = agent_pb2.RunReplicaRequest(
            replica_id=replica_id,
            app_id=app_id,
            image=agent_pb2.ImageRef(
                repository=image_repository,
                digest=image_digest,
            ),
            container_port=container_port,
            env=[agent_pb2.EnvVar(name=k, value=v) for k, v in sorted(env.items())],
            limits=agent_pb2.Limits(
                cpu_millicores=cpu_millicores,
                memory_bytes=memory_bytes,
            ),
        )
        response = await stub.RunReplica(request, timeout=RUN_REPLICA_TIMEOUT)
        return ReplicaResult(
            replica_id=response.replica.replica_id,
            node=node,
            host_port=response.replica.host_port,
        )

    async def close(self) -> None:
        """Close every channel (lifespan shutdown)."""
        await self._builder_channel.close()
        for channel in self._runner_channels.values():
            await channel.close()


def _deploy_result(deploy: agent_pb2.Deploy) -> DeployResult:
    """protobuf Deploy -> DeployResult.

    Unset protobuf fields read as defaults ("" / 0), never None.
    """
    try:
        state = agent_pb2.DeployState.Name(deploy.state)
    except ValueError:
        state = f"{_DEPLOY_STATE_PREFIX}UNKNOWN_{deploy.state}"
    return DeployResult(
        deploy_id=deploy.deploy_id,
        state=state.removeprefix(_DEPLOY_STATE_PREFIX),
        commit_sha=deploy.commit_sha,
        image_repository=deploy.image.repository,
        image_digest=deploy.image.digest,
        error=deploy.error,
    )


class Agents(Protocol):
    """What run_deploy needs from the agents; AgentClients and test fakes fit it."""

    @property
    def runner_names(self) -> list[str]: ...

    async def get_deploy(self, deploy_id: str) -> DeployResult: ...

    async def run_replica(
        self,
        *,
        node: str,
        replica_id: str,
        app_id: str,
        image_repository: str,
        image_digest: str,
        container_port: int,
        env: dict[str, str],
        cpu_millicores: int,
        memory_bytes: int,
    ) -> ReplicaResult: ...
