"""Async gRPC client to the node agents. protobuf stays in this module; RPC errors are not translated (callers get AioRpcError)."""

from dataclasses import dataclass
from typing import Protocol

import grpc
from bult.agent.v1 import agent_pb2, agent_pb2_grpc

START_DEPLOY_TIMEOUT = 10
GET_DEPLOY_TIMEOUT = 10
CANCEL_DEPLOY_TIMEOUT = 10
RUN_REPLICA_TIMEOUT = 300  # includes pulling the image on the node
REMOVE_REPLICA_TIMEOUT = 30
LIST_REPLICAS_TIMEOUT = 10
LOGS_TIMEOUT = 10

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


@dataclass(frozen=True)
class ReplicaInfo:
    """A replica as a node reports it (ListReplicas)."""

    replica_id: str
    app_id: str
    host_port: int
    state: str  # ReplicaState without the prefix, e.g. "RUNNING"


class UnknownNodeError(Exception):
    """No runner with this name is known."""


class Directory(Protocol):
    """Where the agents are; the nodes domain's facade fits it."""

    async def builder_address(self) -> str | None: ...
    async def runner_address(self, name: str) -> str | None: ...
    async def runner_names(self) -> list[str]: ...


@dataclass
class _Channel:
    address: str
    channel: grpc.aio.Channel


CHANNEL_CLOSE_GRACE = 5  # seconds in-flight calls get when a node's address changes


def _no_builder() -> grpc.aio.AioRpcError:
    """Looks like any other builder outage to callers: UNAVAILABLE."""
    return grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        grpc.aio.Metadata(),
        grpc.aio.Metadata(),
        details="no ready builder node",
    )


class AgentClients:
    """gRPC stubs to the builder and the runner nodes.

    A channel is created on first use for the address the directory gives, and replaced
    when a node comes back at another address. Channels are lazy: a node that is down
    does not stop startup.
    """

    def __init__(self, directory: Directory) -> None:
        self._directory = directory
        self._channels: dict[str, _Channel] = {}  # "builder" or "runner:<name>"

    async def runner_names(self) -> list[str]:
        """Every known runner node, ready or not."""
        return await self._directory.runner_names()

    async def _channel_for(self, key: str, address: str) -> grpc.aio.Channel:
        """The channel for `key`, replaced if the node's address changed."""
        current = self._channels.get(key)
        if current is not None and current.address == address:
            return current.channel

        # No await between the lookup and the store: two callers cannot create two channels.
        channel = grpc.aio.insecure_channel(address, options=CHANNEL_OPTIONS)
        self._channels[key] = _Channel(address, channel)
        if current is not None:
            await current.channel.close(CHANNEL_CLOSE_GRACE)
        return channel

    async def _builder_stub(self) -> agent_pb2_grpc.BuildServiceStub:
        address = await self._directory.builder_address()
        if address is None:
            raise _no_builder()
        return agent_pb2_grpc.BuildServiceStub(
            await self._channel_for("builder", address)
        )

    async def _runner_stub(self, node: str) -> agent_pb2_grpc.RuntimeServiceStub:
        address = await self._directory.runner_address(node)
        if address is None:
            raise UnknownNodeError(node)
        return agent_pb2_grpc.RuntimeServiceStub(
            await self._channel_for(f"runner:{node}", address)
        )

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
        builder = await self._builder_stub()
        response = await builder.StartDeploy(request, timeout=START_DEPLOY_TIMEOUT)
        return _deploy_result(response.deploy)

    async def get_deploy(self, deploy_id: str) -> DeployResult:
        """GetDeploy on the builder."""
        request = agent_pb2.GetDeployRequest(deploy_id=deploy_id)
        builder = await self._builder_stub()
        response = await builder.GetDeploy(request, timeout=GET_DEPLOY_TIMEOUT)
        return _deploy_result(response.deploy)

    async def cancel_deploy(self, deploy_id: str) -> DeployResult:
        """CancelDeploy on the builder; a finished build is returned as it is."""
        request = agent_pb2.CancelDeployRequest(deploy_id=deploy_id)
        builder = await self._builder_stub()
        response = await builder.CancelDeploy(request, timeout=CANCEL_DEPLOY_TIMEOUT)
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
        stub = await self._runner_stub(node)

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

    async def remove_replica(self, node: str, replica_id: str) -> None:
        """RemoveReplica on one runner."""
        stub = await self._runner_stub(node)
        await stub.RemoveReplica(
            agent_pb2.RemoveReplicaRequest(replica_id=replica_id),
            timeout=REMOVE_REPLICA_TIMEOUT,
        )

    async def list_replicas(self, node: str) -> list[ReplicaInfo]:
        """ListReplicas on one runner: every bult-managed replica, any app."""
        stub = await self._runner_stub(node)
        response = await stub.ListReplicas(
            agent_pb2.ListReplicasRequest(), timeout=LIST_REPLICAS_TIMEOUT
        )
        return [
            ReplicaInfo(
                replica_id=r.replica_id,
                app_id=r.app_id,
                host_port=r.host_port,
                state=_replica_state(r.state),
            )
            for r in response.replicas
        ]

    async def logs(self, node: str, replica_id: str, tail_lines: int) -> str:
        """The last `tail_lines` lines of a replica's output (Logs without follow)."""
        stub = await self._runner_stub(node)
        call = stub.Logs(
            agent_pb2.LogsRequest(
                replica_id=replica_id, follow=False, tail_lines=tail_lines
            ),
            timeout=LOGS_TIMEOUT,
        )
        chunks = [response.data async for response in call]
        return b"".join(chunks).decode("utf-8", errors="replace")

    async def close(self) -> None:
        """Close every channel."""
        channels, self._channels = self._channels, {}
        for current in channels.values():
            await current.channel.close()


def _replica_state(state: int) -> str:
    """protobuf ReplicaState -> name without the prefix."""
    try:
        name = agent_pb2.ReplicaState.Name(state)
    except ValueError:
        return f"UNKNOWN_{state}"
    return name.removeprefix("REPLICA_STATE_")


def _deploy_result(deploy: agent_pb2.Deploy) -> DeployResult:
    """protobuf Deploy -> DeployResult."""
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
    """What deploys need from the agents; AgentClients and the test fakes fit it."""

    async def runner_names(self) -> list[str]: ...

    async def start_deploy(
        self,
        *,
        deploy_id: str,
        app_id: str,
        repo_url: str,
        branch: str,
        subdir: str,
        dockerfile: str,
    ) -> DeployResult: ...

    async def get_deploy(self, deploy_id: str) -> DeployResult: ...

    async def cancel_deploy(self, deploy_id: str) -> DeployResult: ...

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

    async def remove_replica(self, *, node: str, replica_id: str) -> None: ...

    async def list_replicas(self, node: str) -> list[ReplicaInfo]: ...

    async def logs(self, *, node: str, replica_id: str, tail_lines: int) -> str: ...
