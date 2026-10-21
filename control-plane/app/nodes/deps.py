"""Depends wiring of the nodes domain."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated

from fastapi import Depends, Request

from app.nodes.services.nodes import NodeService, ReplicaHealth, ReplicaUsage

# How many running replicas each node has; the deploys domain supplies it (wired in main).
ReplicaCounts = Callable[[], Awaitable[dict[str, int]]]

# Where a node's replica readings go (node name, readings); the metrics domain supplies it (wired in main).
UsageSink = Callable[[str, Sequence[ReplicaUsage]], Awaitable[None]]

# Where a node's replica states go (node name, states, whether the list is complete); the
# deploys domain supplies it (wired in main).
HealthSink = Callable[[str, Sequence[ReplicaHealth], bool], Awaitable[None]]


def get_node_service(request: Request) -> NodeService:
    """One service per process: it holds the address cache."""
    return request.app.state.node_service


def get_replica_counts(request: Request) -> ReplicaCounts:
    return request.app.state.replica_counts


def get_usage_sink(request: Request) -> UsageSink:
    return request.app.state.usage_sink


def get_health_sink(request: Request) -> HealthSink:
    return request.app.state.health_sink


NodeServiceDep = Annotated[NodeService, Depends(get_node_service)]
ReplicaCountsDep = Annotated[ReplicaCounts, Depends(get_replica_counts)]
UsageSinkDep = Annotated[UsageSink, Depends(get_usage_sink)]
HealthSinkDep = Annotated[HealthSink, Depends(get_health_sink)]
