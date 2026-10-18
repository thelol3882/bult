"""Pydantic schemas of the nodes resource."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.nodes.repositories.nodes import NodeRole
from app.nodes.services.nodes import NodeStatus, NodeView

NODE_NAME_REGEX = r"^[a-z0-9][a-z0-9._-]{0,62}$"
# host:port; a hostname or an IPv4 address (IPv6 literals are not used on the nodes)
ADDRESS_REGEX = r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}:[0-9]{1,5}$"


class CapacityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpus: Annotated[int, Field(ge=0, le=100_000)] = 0
    memory_bytes: Annotated[int, Field(ge=0, le=2**50)] = 0


class HeartbeatIn(BaseModel):
    """Request body of POST /internal/nodes/heartbeat."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=NODE_NAME_REGEX)]
    address: Annotated[str, Field(pattern=ADDRESS_REGEX)]
    role: NodeRole
    version: Annotated[str, Field(max_length=100)] = ""
    capacity: CapacityIn = CapacityIn()


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
