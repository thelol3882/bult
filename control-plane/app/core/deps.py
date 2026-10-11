"""Domain-independent dependencies; they read `app.state` set up in the lifespan."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from app.agents.client import Agents
from app.core.config import Settings
from app.core.events import EventBus, EventCollector
from app.ingress.routes import RouteWriter


def get_settings(request: Request) -> Settings:
    """Settings loaded at startup."""
    return request.app.state.settings


def get_agents(request: Request) -> Agents:
    """gRPC clients to the node agents."""
    return request.app.state.agents


def get_routes(request: Request) -> RouteWriter:
    """The ingress route writer."""
    return request.app.state.routes


def get_event_bus(request: Request) -> EventBus:
    """The application's event bus."""
    return request.app.state.event_bus


EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


async def get_event_collector(bus: EventBusDep) -> AsyncIterator[EventCollector]:
    """Deliver queued events after the endpoint succeeds (function scope: before the response is sent)."""
    collector = bus.collector()
    yield collector
    await collector.drain()


SettingsDep = Annotated[Settings, Depends(get_settings)]
AgentsDep = Annotated[Agents, Depends(get_agents)]
RoutesDep = Annotated[RouteWriter, Depends(get_routes)]
EventCollectorDep = Annotated[
    EventCollector, Depends(get_event_collector, scope="function")
]
