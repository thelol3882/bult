"""Replica health: deaths, hung apps, crash loops, dead nodes, strays, scale-down order."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

import grpc
import pytest

from app.apps.services.facade import AppsFacade
from app.deploys.repositories.deploys import Deploy
from app.deploys.repositories.replicas import Replica
from app.deploys.services.health import (
    FAILURE_WINDOW,
    MAX_FAILURES,
    STALE_GRACE,
    UNHEALTHY_REPLACE_AFTER,
    HealthState,
    Observation,
    ReplicaHealthService,
    backoff,
    death_changes,
    to_view,
)
from app.deploys.services.reconciler import Reconciler
from app.deploys.services.routing import current_routes
from app.deploys.services.scheduler import pick_victims
from app.deploys.uow import InMemoryDeploysUoW
from app.nodes.services.facade import NodesFacade
from tests.fakes import (
    HOST_PORT,
    FakeAgentClients,
    FakeApps,
    FakeClock,
    FakeNodes,
    add_running_deploy,
    rpc_error,
)

NODE_B = "node-b"
EXIT_1 = Observation("d1-r0", "exited", exit_code=1)


class Harness:
    """A reconciler and the heartbeat service on the same in-memory fakes."""

    def __init__(
        self,
        uow: InMemoryDeploysUoW,
        agents: FakeAgentClients,
        nodes: FakeNodes,
        clock: FakeClock,
    ) -> None:
        self.uow, self.agents, self.nodes, self.clock = uow, agents, nodes, clock
        self.state = HealthState()
        self.routes_applied = 0

        async def reapply(what: str) -> int | None:
            self.routes_applied += 1
            return self.routes_applied

        self.reconciler = Reconciler(
            self.state,
            lambda: uow,
            agents,
            cast(NodesFacade, nodes),
            cast(AppsFacade, FakeApps()),
            reapply,
            "10.0.0.1",
            clock=clock,
        )
        self.health = ReplicaHealthService(lambda: uow, self.state, clock=clock)

    async def deploy(self, placements: list[tuple[str, int]]) -> None:
        await add_running_deploy(self.uow, "d1", "blog", placements)
        for i, (node, port) in enumerate(placements):
            self.agents.seed_replica(f"d1-r{i}", "blog", node=node, port=port)
            await self.uow.replicas.update(
                f"d1-r{i}", placed_at=self.clock.now - timedelta(hours=1)
            )

    async def row(self, index: int = 0) -> Replica:
        [row] = await self.uow.replicas.get_running([f"d1-r{index}"])
        return row

    async def beat(self, node: str, *obs: Observation, complete: bool = False):
        result = await self.health.record(node, obs, complete)
        if result.routes_changed:
            self.state.signal.routes_changed()
        for rid in result.garbage:
            self.state.signal.collect(node, rid)
        return result

    async def tick(self) -> None:
        await self.reconciler.tick()
        await self.reconciler.join()

    async def upstreams(self) -> list[tuple[str, int]]:
        routes = await current_routes(self.uow, cast(NodesFacade, self.nodes))
        return [(u.node_ip, u.host_port) for r in routes for u in r.upstreams]


@pytest.fixture
def h(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    nodes: FakeNodes,
    clock: FakeClock,
) -> Harness:
    nodes.add(NODE_B, "10.0.0.6:50051")
    return Harness(deploys_uow, agents, nodes, clock)


def run(coro):
    return asyncio.run(coro)


# --- rules ---------------------------------------------------------------------------


def test_backoff_doubles_from_ten_seconds_and_stops_at_five_minutes():
    assert [backoff(n).total_seconds() for n in (1, 2, 3, 4, 5, 6, 10)] == [
        10, 20, 40, 80, 160, 300, 300,
    ]  # fmt: skip


def test_the_fifth_death_within_the_window_is_a_crash_loop(clock: FakeClock):
    row = Replica("d1-r0", "d1", 0, "node-a", HOST_PORT)
    states = []
    for _ in range(MAX_FAILURES):
        clock.advance(60)
        changes = death_changes(row, clock.now, "exited", 1, "exited with code 1")
        row = replace(row, **changes)
        states.append(row.state)

    assert states == ["exited"] * (MAX_FAILURES - 1) + ["crashloop"]
    assert row.retry_at is None and row.reason == "crash loop: exited with code 1"


def test_deaths_outside_the_window_do_not_count(clock: FakeClock):
    row = Replica("d1-r0", "d1", 0, "node-a", HOST_PORT)
    for _ in range(MAX_FAILURES - 1):
        row = replace(row, **death_changes(row, clock.now, "exited", 1, "x"))
    clock.advance(FAILURE_WINDOW.total_seconds() + 1)

    changes = death_changes(row, clock.now, "exited", 1, "x")

    assert changes["state"] == "exited" and len(changes["failures"]) == 1
    assert changes["retry_at"] == clock.now + backoff(1)


# --- a container dies ----------------------------------------------------------------


def test_a_dead_replica_leaves_the_upstream_at_once_and_is_replaced_after_its_backoff(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001), (NODE_B, 30002)])
        h.agents.log_text = "boom\nTraceback"
        assert len(await h.upstreams()) == 2

        result = await h.beat("node-a", EXIT_1)

        assert result.routes_changed and h.state.signal.routes_dirty
        assert await h.upstreams() == [("10.0.0.6", 30002)]
        row = await h.row()
        assert (row.state, row.exit_code, row.reason) == ("exited", 1, "exited with code 1")
        assert row.retry_at == h.clock.now + backoff(1)

        await h.tick()  # within the backoff: nothing is started, but the routes are re-rendered
        assert h.agents.run_calls == [] and h.routes_applied == 1

        h.clock.advance(11)
        await h.tick()

        # the dead container is removed first (same name), then started on the same node
        assert h.agents.remove_calls == [{"node": "node-a", "replica_id": "d1-r0"}]
        [call] = h.agents.run_calls
        assert (call["node"], call["replica_id"]) == ("node-a", "d1-r0")
        row = await h.row()
        assert (row.state, row.healthy, row.node) == ("running", True, "node-a")
        assert row.log_tail == "boom\nTraceback" and not row.tail_pending
        await h.tick()  # the replacement woke the reconciler: routes follow
        assert len(await h.upstreams()) == 2 and h.routes_applied == 2

    run(scenario())


def test_a_replacement_goes_to_another_node_when_the_old_one_cannot_remove_the_container(
    h: Harness,
):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        await h.beat("node-a", EXIT_1)
        h.agents.remove_error = rpc_error(grpc.StatusCode.UNAVAILABLE)
        h.clock.advance(11)

        await h.tick()

        [call] = h.agents.run_calls
        assert call["node"] == NODE_B
        assert (await h.row()).node == NODE_B

    run(scenario())


def test_a_report_of_the_previous_container_does_not_count_as_a_new_death(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        old = Observation(
            "d1-r0", "exited", exit_code=1, finished_at=h.clock.now - timedelta(hours=2)
        )

        result = await h.beat("node-a", old)

        assert not result.routes_changed and (await h.row()).state == "running"

    run(scenario())


def test_a_crash_loop_stops_the_replacements_and_keeps_the_reason(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        h.agents.log_text = "\n".join(f"line {i}" for i in range(30))
        for attempt in range(MAX_FAILURES):
            await h.beat("node-a", Observation("d1-r0", "exited", exit_code=3))
            await h.tick()  # fetches the tail; replaces once the backoff has passed
            h.clock.advance(100)
            await h.tick()
            if attempt < MAX_FAILURES - 1:
                assert (await h.row()).state == "running"
        runs = len(h.agents.run_calls)

        row = await h.row()
        assert (row.state, row.exit_code, row.retry_at) == ("crashloop", 3, None)
        assert row.reason == "crash loop: exited with code 3"
        assert row.log_tail.splitlines() == [f"line {i}" for i in range(10, 30)]
        assert runs == MAX_FAILURES - 1

        h.clock.advance(3600)
        await h.tick()
        assert len(h.agents.run_calls) == runs  # no more replacements
        assert await h.upstreams() == []

        # reports about a crash-looping slot change nothing
        assert not (await h.beat("node-a", Observation("d1-r0", "running"))).routes_changed

    run(scenario())


def test_a_scale_gives_a_crash_looping_replica_another_chance(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        await h.uow.replicas.update(
            "d1-r0", state="crashloop", failures=(h.clock.now,) * MAX_FAILURES
        )

        assert await h.uow.replicas.reset_crashloops("d1") == 1
        await h.tick()

        row = await h.row()
        assert (row.state, row.failures) == ("running", ()) and len(h.agents.run_calls) == 1

    run(scenario())


# --- a hung app ----------------------------------------------------------------------


def test_a_hung_replica_leaves_the_upstream_and_is_replaced_after_a_minute(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001), (NODE_B, 30002)])

        result = await h.beat("node-a", Observation("d1-r0", "running", healthy=False))

        assert result.routes_changed
        assert await h.upstreams() == [("10.0.0.6", 30002)]
        assert (await h.row()).state == "running"  # alive, only out of the upstream
        views = await _view_statuses(h)
        assert views == ["unhealthy", "running"]

        h.clock.advance(UNHEALTHY_REPLACE_AFTER.total_seconds() - 1)
        await h.tick()
        assert h.agents.run_calls == []  # a stall that ends by itself is not punished

        h.clock.advance(2)
        await h.tick()  # recorded as a death with its backoff; replaced right after
        h.clock.advance(11)
        await h.tick()

        row = await h.row()
        assert (row.state, row.reason, len(row.failures)) == ("running", "health check failed", 1)
        assert len(h.agents.run_calls) == 1
        assert len(await h.upstreams()) == 2

    run(scenario())


def test_a_replica_that_recovers_returns_to_the_upstream(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        await h.beat("node-a", Observation("d1-r0", "running", healthy=False))
        assert await h.upstreams() == []

        result = await h.beat("node-a", Observation("d1-r0", "running", healthy=True))

        assert result.routes_changed and len(await h.upstreams()) == 1
        assert (await h.row()).unhealthy_since is None

    run(scenario())


async def _view_statuses(h: Harness) -> list[str]:
    rows = await h.uow.replicas.list_running(["d1"])
    return [to_view(r, True, h.clock.now).status for r in rows]


# --- dead nodes and strays -----------------------------------------------------------


def test_the_replicas_of_a_dead_node_are_rescheduled_at_once_without_counting_a_failure(
    h: Harness,
):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001), ("node-a", 30002)])
        h.nodes.set_dead("node-a")

        await h.tick()

        assert sorted(c["replica_id"] for c in h.agents.run_calls) == ["d1-r0", "d1-r1"]
        for index in (0, 1):
            row = await h.row(index)
            assert (row.node, row.state, row.failures) == (NODE_B, "running", ())
        assert len(await h.upstreams()) == 2

    run(scenario())


def test_a_replica_stays_lost_while_no_node_can_take_it(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        h.nodes.set_dead("node-a")
        h.nodes.set_dead(NODE_B)

        await h.tick()

        row = await h.row()
        assert (row.state, row.reason) == ("lost", "node is down") and h.agents.run_calls == []

    run(scenario())


def test_a_node_that_returns_has_its_stale_containers_removed(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        h.nodes.set_dead("node-a")
        await h.tick()  # d1-r0 now runs on node-b
        h.nodes.set_dead("node-a", False)
        stale = Observation("d1-r0", "running")

        first = await h.beat("node-a", stale)  # seen, but not for long enough yet
        assert first.garbage == ()
        h.clock.advance(STALE_GRACE.total_seconds())
        second = await h.beat("node-a", stale)

        assert second.garbage == ("d1-r0",)
        h.agents.remove_calls.clear()
        await h.tick()
        assert h.agents.remove_calls == [{"node": "node-a", "replica_id": "d1-r0"}]
        assert (await h.row()).node == NODE_B  # the replacement is untouched

    run(scenario())


def test_containers_of_a_live_or_starting_deploy_are_not_strays(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        await h.uow.deploys.add(
            Deploy(id="d2", app_name="other", status="starting")
        )
        reported = [Observation("d1-r0", "running"), Observation("d2-r0", "running")]

        await h.beat("node-a", *reported)
        h.clock.advance(STALE_GRACE.total_seconds() * 2)
        result = await h.beat("node-a", *reported)

        assert result.garbage == ()

    run(scenario())


def test_a_stray_of_a_finished_deploy_is_removed_after_the_grace(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])
        stray = Observation("gone-r0", "running")

        await h.beat("node-a", stray)
        h.clock.advance(STALE_GRACE.total_seconds())

        assert (await h.beat("node-a", stray)).garbage == ("gone-r0",)

    run(scenario())


def test_a_container_missing_from_a_complete_report_is_replaced(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])

        result = await h.beat("node-a", complete=True)  # the node reports an empty list

        assert result.routes_changed
        row = await h.row()
        assert (row.state, row.reason) == ("exited", "container is gone")

    run(scenario())


def test_an_incomplete_report_never_condemns_a_replica(h: Harness):
    async def scenario() -> None:
        await h.deploy([("node-a", 30001)])

        await h.beat("node-a", Observation("other-r0", "running"), complete=False)

        assert (await h.row()).state == "running"

    run(scenario())


# --- scale-down order ----------------------------------------------------------------


def _row(index: int, node: str, age: int, **kw: Any) -> Replica:
    placed: Callable[[int], datetime] = lambda a: datetime(2026, 10, 18, 12) - timedelta(hours=a)
    return Replica(f"d1-r{index}", "d1", index, node, HOST_PORT + index, placed_at=placed(age), **kw)


def test_scale_down_drops_dead_replicas_first():
    rows = [_row(0, "a", 3), _row(1, "a", 2, state="crashloop"), _row(2, "b", 1, healthy=False), _row(3, "b", 5)]

    assert {r.index for r in pick_victims(rows, 2, {"a", "b"})} == {1, 2}


def test_a_dead_replica_goes_before_a_healthy_one_on_a_busier_node():
    rows = [_row(0, "a", 1), _row(1, "a", 2), _row(2, "a", 3), _row(3, "b", 9, state="crashloop")]

    assert [r.index for r in pick_victims(rows, 1, {"a", "b"})] == [3]
    assert [r.index for r in pick_victims(rows[:3], 1, {"b"})] == [0]  # a is not ready: all equal


def test_scale_down_then_takes_from_the_busiest_node_and_the_newest_on_a_tie():
    rows = [_row(0, "a", 4), _row(1, "a", 3), _row(2, "a", 1), _row(3, "b", 2)]

    assert [r.index for r in pick_victims(rows, 1, {"a", "b"})] == [2]  # a is busiest, 2 newest
    # one at a time: after 2 goes, a still holds more than b
    assert [r.index for r in pick_victims(rows, 2, {"a", "b"})] == [2, 1]

def test_scale_down_balances_instead_of_emptying_one_node():
    rows = [_row(0, "a", 4), _row(1, "a", 3), _row(2, "b", 2), _row(3, "b", 1)]

    assert {r.node for r in pick_victims(rows, 2, {"a", "b"})} == {"a", "b"}
