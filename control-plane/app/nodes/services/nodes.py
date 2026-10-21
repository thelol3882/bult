"""Nodes domain rules: heartbeats, status from silence, and the directory of agent addresses."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.core.config import Settings
from app.nodes.errors import InvalidNodeTokenError
from app.nodes.repositories.nodes import Node, NodeRole
from app.nodes.services.tokens import NodeTokens
from app.nodes.uow import NodesUoW

NodeStatus = Literal["ready", "unhealthy", "dead"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ReplicaUsage:
    """CPU and memory of one replica, as its node measured them."""

    replica_id: str
    cpu_cores: float
    cpu_limit_pct: float
    mem_bytes: int
    mem_limit_bytes: int


@dataclass(frozen=True)
class ReplicaHealth:
    """State of one replica container, as its node saw it."""

    replica_id: str
    state: Literal["running", "exited", "oom"]
    exit_code: int | None = None
    oom_killed: bool = False
    healthy: bool = True
    finished_at: datetime | None = None


@dataclass(frozen=True)
class NodeReport:
    """What a node says about itself in a heartbeat."""

    name: str
    address: str
    role: NodeRole
    version: str = ""
    cpus: int = 0
    memory_bytes: int = 0
    replicas: tuple[ReplicaUsage, ...] = ()  # absent in heartbeats of older agents and builders
    health: tuple[ReplicaHealth, ...] = ()
    reports_replicas: bool = False  # the list is complete: a replica missing from it is gone


@dataclass(frozen=True)
class NodeView:
    """A node as the API shows it: no address, no token."""

    name: str
    role: NodeRole
    status: NodeStatus
    last_seen_at: datetime
    version: str
    cpus: int
    memory_bytes: int


@dataclass(frozen=True)
class RunnerNode:
    """A node that can run replicas."""

    name: str
    address: str
    ready: bool
    dead: bool = False  # silent so long that its replicas are rescheduled


class NodeService:
    def __init__(
        self,
        uow_factory: Callable[[], NodesUoW],
        settings: Settings,
        *,
        clock: Callable[[], datetime] = _utcnow,
        monotonic: Callable[[], float] = time.monotonic,
        cache_ttl: float = 1.0,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = NodeTokens(settings.node_tokens)
        self._ttl = settings.node_ttl_seconds
        self._dead_after = settings.node_dead_seconds
        self._static_builder = settings.builder
        self._static_runners = settings.runners
        self._clock = clock
        self._monotonic = monotonic
        self._cache_ttl = cache_ttl
        # Every RPC asks for an address: a short cache keeps that off the database.
        self._cache: tuple[float, list[Node]] | None = None

    async def heartbeat(self, report: NodeReport, token: str | None) -> Node:
        """Register or refresh a node. InvalidNodeTokenError unless the token is bound to this name."""
        if not self._tokens.verify(report.name, token):
            raise InvalidNodeTokenError()

        node = Node(
            name=report.name,
            address=report.address,
            role=report.role,
            version=report.version,
            cpus=report.cpus,
            memory_bytes=report.memory_bytes,
            last_seen_at=self._clock(),
        )
        async with self._uow_factory() as uow:
            stored = await uow.nodes.upsert(node)
            await uow.commit()
        self._cache = None
        return stored

    def status_of(self, node: Node) -> NodeStatus:
        silent = (self._clock() - node.last_seen_at).total_seconds()
        if silent <= self._ttl:
            return "ready"
        return "unhealthy" if silent <= self._dead_after else "dead"

    async def views(self) -> list[NodeView]:
        """Registered nodes with their status (for the API)."""
        return [
            NodeView(
                name=n.name,
                role=n.role,
                status=self.status_of(n),
                last_seen_at=n.last_seen_at,
                version=n.version,
                cpus=n.cpus,
                memory_bytes=n.memory_bytes,
            )
            for n in await self._load(fresh=True)
        ]

    async def statuses(self) -> dict[str, NodeStatus]:
        """Ready or unhealthy for every registered node, read fresh (for the monitor, which
        only cares about routing: a dead node is unhealthy too)."""
        return {
            n.name: "ready" if self.status_of(n) == "ready" else "unhealthy"
            for n in await self._load(fresh=True)
        }

    # The directory: where the agents are. Registered nodes win; the static configuration
    # (BULT_BUILDER / BULT_RUNNERS) is used for a role only while no node of that role
    # has registered.

    async def runners(self) -> list[RunnerNode]:
        registered = [n for n in await self._load() if n.runs_replicas]
        if registered:
            return [
                RunnerNode(
                    n.name,
                    n.address,
                    self.status_of(n) == "ready",
                    self.status_of(n) == "dead",
                )
                for n in registered
            ]
        return [RunnerNode(name, addr, True) for name, addr in self._static_runners.items()]

    async def builder_address(self) -> str | None:
        """Address of a ready builder; None when builders are registered but none is ready."""
        registered = [n for n in await self._load() if n.builds]
        if not registered:
            return self._static_builder or None
        for node in registered:
            if self.status_of(node) == "ready":
                return node.address
        return None

    async def runner_address(self, name: str) -> str | None:
        """Address of a known runner, ready or not (RemoveReplica still tries an unhealthy node)."""
        for runner in await self.runners():
            if runner.name == name:
                return runner.address
        return None

    async def runner_names(self) -> list[str]:
        return [r.name for r in await self.runners()]

    async def _load(self, fresh: bool = False) -> list[Node]:
        now = self._monotonic()
        if not fresh and self._cache is not None and now - self._cache[0] < self._cache_ttl:
            return self._cache[1]
        async with self._uow_factory() as uow:
            nodes = await uow.nodes.list()
        self._cache = (now, nodes)
        return nodes
