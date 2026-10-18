"""Depends wiring of the nodes domain."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from app.nodes.services.nodes import NodeService

# How many running replicas each node has; the deploys domain supplies it (wired in main).
ReplicaCounts = Callable[[], Awaitable[dict[str, int]]]


def get_node_service(request: Request) -> NodeService:
    """One service per process: it holds the address cache."""
    return request.app.state.node_service


def get_replica_counts(request: Request) -> ReplicaCounts:
    return request.app.state.replica_counts


NodeServiceDep = Annotated[NodeService, Depends(get_node_service)]
ReplicaCountsDep = Annotated[ReplicaCounts, Depends(get_replica_counts)]
