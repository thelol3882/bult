"""Replica storage behind a Protocol.

A replica row says where a deploy's container runs. Rows stay after a replica is retired
(`removed`), so the history of a deploy keeps showing where it ran.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

ReplicaStatus = Literal["running", "removed"]


def replica_id(deploy_id: str, index: int) -> str:
    """The name of the replica on the node (and its row)."""
    return f"{deploy_id}-r{index}"


@dataclass
class Replica:
    """One container of a deploy."""

    id: str
    deploy_id: str
    index: int
    node: str
    host_port: int
    status: ReplicaStatus = "running"
    created_at: datetime | None = None  # set by storage on add


@dataclass(frozen=True)
class ReplicaView:
    """A replica as the API shows it; `unhealthy` means its node stopped reporting."""

    index: int
    node: str
    host_port: int
    status: Literal["running", "unhealthy"]


class ReplicaRepository(Protocol):
    """Storage only; placement rules live in the scheduler and the runner."""

    async def save(self, replica: Replica) -> bool:
        """Insert or update by id as `running`; False if the deploy no longer exists."""
        ...

    async def list_running(self, deploy_ids: Iterable[str]) -> list[Replica]:
        """Running replicas of these deploys, ordered by (deploy, index)."""
        ...

    async def list_all_running(self) -> list[Replica]:
        """Every running replica, any deploy."""
        ...

    async def get_running(self, replica_ids: Iterable[str]) -> list[Replica]:
        """The running replicas with these ids; unknown and removed ids are left out."""
        ...

    async def mark_removed(self, replica_ids: Iterable[str]) -> None: ...

    async def count_running_by_node(self) -> dict[str, int]: ...


class InMemoryReplicaRepository:
    """Dict keyed by id; also the test fake."""

    def __init__(self) -> None:
        self._replicas: dict[str, Replica] = {}

    def forget_deploys(self, deploy_ids: Iterable[str]) -> None:
        """What ON DELETE CASCADE does."""
        gone = set(deploy_ids)
        self._replicas = {
            k: r for k, r in self._replicas.items() if r.deploy_id not in gone
        }

    async def save(self, replica: Replica) -> bool:
        previous = self._replicas.get(replica.id)
        created_at = previous.created_at if previous else datetime.now(UTC)
        self._replicas[replica.id] = replace(
            replica, status="running", created_at=created_at
        )
        return True

    async def list_running(self, deploy_ids: Iterable[str]) -> list[Replica]:
        wanted = set(deploy_ids)
        found = [
            r
            for r in self._replicas.values()
            if r.deploy_id in wanted and r.status == "running"
        ]
        return [replace(r) for r in sorted(found, key=lambda r: (r.deploy_id, r.index))]

    async def list_all_running(self) -> list[Replica]:
        running = [r for r in self._replicas.values() if r.status == "running"]
        return [replace(r) for r in sorted(running, key=lambda r: (r.deploy_id, r.index))]

    async def get_running(self, replica_ids: Iterable[str]) -> list[Replica]:
        found = [self._replicas.get(rid) for rid in replica_ids]
        return [replace(r) for r in found if r is not None and r.status == "running"]

    async def mark_removed(self, replica_ids: Iterable[str]) -> None:
        for rid in replica_ids:
            if rid in self._replicas:
                self._replicas[rid] = replace(self._replicas[rid], status="removed")

    async def count_running_by_node(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._replicas.values():
            if r.status == "running":
                counts[r.node] = counts.get(r.node, 0) + 1
        return counts
