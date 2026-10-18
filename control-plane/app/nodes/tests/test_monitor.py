"""The monitor calls back when a node flips between ready and unhealthy."""

import asyncio

import pytest

from app.nodes.services.monitor import NodeMonitor
from app.nodes.services.nodes import NodeReport, NodeService
from tests.fakes import NODE_TOKENS, FakeClock


class Counter:
    def __init__(self) -> None:
        self.calls = 0
        self.fail_next = False

    async def __call__(self) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("routes could not be applied")
        self.calls += 1


def _beat(service: NodeService, name: str) -> None:
    address = {"node-a": "10.0.0.5:50051", "node-b": "10.0.0.6:50051"}[name]
    asyncio.run(
        service.heartbeat(NodeReport(name, address, "runner"), NODE_TOKENS[name])
    )


def _check(monitor: NodeMonitor) -> bool:
    return asyncio.run(monitor.check())


def _monitor(service: NodeService, on_change: Counter) -> NodeMonitor:
    return NodeMonitor(service, on_change, interval=3)


def test_the_first_check_is_a_baseline_when_everything_is_ready(node_service: NodeService):
    on_change = Counter()
    _beat(node_service, "node-a")

    assert _check(_monitor(node_service, on_change)) is False
    assert on_change.calls == 0


def test_the_first_check_refreshes_routes_if_a_node_is_already_unhealthy(
    node_service: NodeService, clock: FakeClock
):
    on_change = Counter()
    _beat(node_service, "node-a")
    clock.advance(30)

    assert _check(_monitor(node_service, on_change)) is True
    assert on_change.calls == 1


def test_going_unhealthy_and_coming_back_each_call_back_once(
    node_service: NodeService, clock: FakeClock
):
    on_change = Counter()
    monitor = _monitor(node_service, on_change)
    _beat(node_service, "node-a")
    _beat(node_service, "node-b")
    assert _check(monitor) is False

    clock.advance(10)
    _beat(node_service, "node-b")
    assert _check(monitor) is False  # node-a is quiet, but not for 15 s yet

    clock.advance(6)
    _beat(node_service, "node-b")
    assert _check(monitor) is True  # node-a crossed the threshold
    assert _check(monitor) is False  # nothing new
    assert on_change.calls == 1

    _beat(node_service, "node-a")
    assert _check(monitor) is True  # it is back
    assert _check(monitor) is False
    assert on_change.calls == 2


def test_a_new_node_does_not_touch_the_routes(node_service: NodeService):
    on_change = Counter()
    monitor = _monitor(node_service, on_change)
    _beat(node_service, "node-a")
    _check(monitor)

    _beat(node_service, "node-b")

    assert _check(monitor) is False
    assert on_change.calls == 0


def test_a_failed_callback_is_retried_on_the_next_check(
    node_service: NodeService, clock: FakeClock
):
    on_change = Counter()
    monitor = _monitor(node_service, on_change)
    _beat(node_service, "node-a")
    _check(monitor)
    clock.advance(16)
    on_change.fail_next = True

    with pytest.raises(RuntimeError):
        _check(monitor)

    assert _check(monitor) is True
    assert on_change.calls == 1
