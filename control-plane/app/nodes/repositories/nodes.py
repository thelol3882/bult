"""Node storage behind a Protocol."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

NodeRole = Literal["builder", "runner", "both"]


@dataclass(frozen=True)
class Node:
    """A node agent that has reported in at least once."""

    name: str
    address: str  # host:port the control plane dials
    role: NodeRole
    last_seen_at: datetime
    version: str = ""
    cpus: int = 0
    memory_bytes: int = 0
    created_at: datetime | None = None  # set by storage on first upsert

    @property
    def runs_replicas(self) -> bool:
        return self.role in ("runner", "both")

    @property
    def builds(self) -> bool:
        return self.role in ("builder", "both")


class NodeRepository(Protocol):
    """Storage only; domain rules live in NodeService."""

    async def upsert(self, node: Node) -> Node:
        """Insert or replace by name; created_at stays from the first insert."""
        ...

    async def list(self) -> list[Node]:
        """Every node, ordered by name."""
        ...


class InMemoryNodeRepository:
    """Dict keyed by name; also the test fake."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    async def upsert(self, node: Node) -> Node:
        previous = self._nodes.get(node.name)
        created_at = previous.created_at if previous else datetime.now(UTC)
        stored = replace(node, created_at=created_at)
        self._nodes[node.name] = stored
        return stored

    async def list(self) -> list[Node]:
        return sorted(self._nodes.values(), key=lambda n: n.name)
