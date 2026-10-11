"""In-process event bus; delivery rules: docs/architecture/control-plane-structure.md (rule 3)."""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

type Handler[E] = Callable[[E], Awaitable[None]]


class EventPublisher(Protocol):
    """What services need: queue an event."""

    def publish(self, event: object) -> None: ...


class EventBus:
    """Subscriptions by exact event type; one instance per app."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler[Any]]] = defaultdict(list)

    def subscribe[E](self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers[event_type].append(handler)

    async def dispatch(self, event: object) -> None:
        """Await handlers in subscription order; the first exception propagates."""
        for handler in self._handlers[type(event)]:
            await handler(event)

    def collector(self) -> "EventCollector":
        return EventCollector(self)


class EventCollector:
    """Per-request queue of undelivered events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queue: list[object] = []

    def publish(self, event: object) -> None:
        self._queue.append(event)

    async def drain(self) -> None:
        """Deliver queued events in order, including ones handlers publish meanwhile."""
        while self._queue:
            event = self._queue.pop(0)
            await self._bus.dispatch(event)
