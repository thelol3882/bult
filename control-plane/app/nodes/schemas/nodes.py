"""Pydantic schemas of the nodes resource."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.nodes.repositories.nodes import NodeRole
from app.nodes.services.nodes import NodeStatus, NodeView, ReplicaHealth, ReplicaUsage

NODE_NAME_REGEX = r"^[a-z0-9][a-z0-9._-]{0,62}$"
# host:port; a hostname or an IPv4 address (IPv6 literals are not used on the nodes)
ADDRESS_REGEX = r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}:[0-9]{1,5}$"


class CapacityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpus: Annotated[int, Field(ge=0, le=100_000)] = 0
    memory_bytes: Annotated[int, Field(ge=0, le=2**50)] = 0


class ReplicaReportIn(BaseModel):
    """One replica in a heartbeat: its state and health, and its usage while it runs.

    Older agents send the usage fields only; the state fields are then absent.
    """

    model_config = ConfigDict(extra="forbid")

    replica_id: Annotated[str, Field(min_length=1, max_length=200)]
    state: Literal["running", "exited", "oom"] | None = None
    exit_code: Annotated[int, Field(ge=-1, le=1000)] | None = None
    oom_killed: bool = False
    healthy: bool = True
    finished_at: datetime | None = None
    cpu_cores: Annotated[float, Field(ge=0, le=100_000, allow_inf_nan=False)] | None = None
    cpu_limit_pct: Annotated[float, Field(ge=0, le=10_000_000, allow_inf_nan=False)] | None = None
    mem_bytes: Annotated[int, Field(ge=0, le=2**50)] | None = None
    mem_limit_bytes: Annotated[int, Field(ge=0, le=2**62)] | None = None

    @model_validator(mode="after")
    def _usage_whole_and_entry_not_empty(self) -> "ReplicaReportIn":
        given = [
            v is not None
            for v in (self.cpu_cores, self.cpu_limit_pct, self.mem_bytes, self.mem_limit_bytes)
        ]
        if any(given) and not all(given):
            raise ValueError("a usage reading needs all of its fields")
        if not any(given) and self.state is None:
            raise ValueError("a replica entry needs a state or a usage reading")
        return self

    def usage(self) -> ReplicaUsage | None:
        """The reading, if the node sent a complete one."""
        if (
            self.cpu_cores is None
            or self.cpu_limit_pct is None
            or self.mem_bytes is None
            or self.mem_limit_bytes is None
        ):
            return None
        return ReplicaUsage(
            self.replica_id,
            self.cpu_cores,
            self.cpu_limit_pct,
            self.mem_bytes,
            self.mem_limit_bytes,
        )

    def health(self) -> ReplicaHealth | None:
        if self.state is None:
            return None
        return ReplicaHealth(
            self.replica_id,
            self.state,
            self.exit_code,
            self.oom_killed,
            self.healthy,
            self.finished_at,
        )


class HeartbeatIn(BaseModel):
    """Request body of POST /internal/nodes/heartbeat."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=NODE_NAME_REGEX)]
    address: Annotated[str, Field(pattern=ADDRESS_REGEX)]
    role: NodeRole
    version: Annotated[str, Field(max_length=100)] = ""
    capacity: CapacityIn = CapacityIn()
    replicas: Annotated[list[ReplicaReportIn], Field(max_length=500)] = []
    reports_replicas: bool = False


class NodeOut(BaseModel):
    """A node as the API returns it."""

    name: str
    role: NodeRole
    status: NodeStatus
    last_seen_at: datetime
    replicas: int  # running replicas placed on the node
    version: str
    cpus: int
    memory_bytes: int

    @classmethod
    def from_view(cls, view: NodeView, replicas: int) -> "NodeOut":
        return cls(
            name=view.name,
            role=view.role,
            status=view.status,
            last_seen_at=view.last_seen_at,
            replicas=replicas,
            version=view.version,
            cpus=view.cpus,
            memory_bytes=view.memory_bytes,
        )
