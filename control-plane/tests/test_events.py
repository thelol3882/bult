"""The in-process event bus."""

import asyncio
import functools
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.deps import EventCollectorDep
from app.core.events import EventBus


def run_async(test: Callable[[], Coroutine[Any, Any, None]]) -> Callable[[], None]:
    """Run an async test in its own loop (no pytest-asyncio)."""

    @functools.wraps(test)
    def wrapper() -> None:
        asyncio.run(test())

    return wrapper


@dataclass(frozen=True)
class Ping:
    n: int


@dataclass(frozen=True)
class Other:
    pass


@run_async
async def test_publish_without_drain_calls_no_handler():
    bus, seen = EventBus(), []

    async def handler(e: Ping) -> None:
        seen.append(e)

    bus.subscribe(Ping, handler)
    bus.collector().publish(Ping(1))
    assert seen == []


@run_async
async def test_drain_awaits_handlers_in_order_and_only_matching_type():
    bus, seen = EventBus(), []

    async def first(e: Ping) -> None:
        seen.append(("first", e.n))

    async def second(e: Ping) -> None:
        seen.append(("second", e.n))

    async def other(e: Other) -> None:
        seen.append(("other", e))

    for h in (first, second):
        bus.subscribe(Ping, h)
    bus.subscribe(Other, other)

    c = bus.collector()
    c.publish(Ping(1))
    c.publish(Ping(2))
    await c.drain()

    assert seen == [("first", 1), ("second", 1), ("first", 2), ("second", 2)]
    await c.drain()  # nothing is delivered twice
    assert len(seen) == 4


@run_async
async def test_handler_exception_propagates():
    bus = EventBus()

    async def boom(e: Ping) -> None:
        raise RuntimeError("handler failed")

    bus.subscribe(Ping, boom)
    c = bus.collector()
    c.publish(Ping(1))
    with pytest.raises(RuntimeError, match="handler failed"):
        await c.drain()


@run_async
async def test_dispatch_delivers_immediately_outside_a_request():
    bus, seen = EventBus(), []

    async def handler(e: Ping) -> None:
        seen.append(e.n)

    bus.subscribe(Ping, handler)
    await bus.dispatch(Ping(7))
    assert seen == [7]


def _mini_app(bus: EventBus) -> FastAPI:
    app = FastAPI()
    app.state.event_bus = bus

    @app.post("/ok")
    async def ok(events: EventCollectorDep) -> dict[str, str]:
        events.publish(Ping(1))
        return {"status": "ok"}

    @app.post("/fail")
    async def fail(events: EventCollectorDep) -> None:
        events.publish(Ping(2))
        raise RuntimeError("endpoint failed")

    return app


def test_endpoint_exception_discards_events():
    bus, seen = EventBus(), []

    async def handler(e: Ping) -> None:
        seen.append(e)

    bus.subscribe(Ping, handler)
    client = TestClient(_mini_app(bus), raise_server_exceptions=False)

    assert client.post("/fail").status_code == 500
    assert seen == []
    assert client.post("/ok").status_code == 200
    assert seen == [Ping(1)]


def test_handler_failure_becomes_a_500_not_a_success():
    bus = EventBus()

    async def boom(e: Ping) -> None:
        raise RuntimeError("handler failed")

    bus.subscribe(Ping, boom)
    client = TestClient(_mini_app(bus), raise_server_exceptions=False)
    assert client.post("/ok").status_code == 500
