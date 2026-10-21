"""Node status from silence, GET /nodes, and the directory with its static fallback."""

import asyncio

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.nodes.services.nodes import NodeReport, NodeService
from app.nodes.uow import InMemoryNodesUoW
from tests.fakes import NODE_TOKENS, FakeClock, add_running_deploy


def _beat(
    service: NodeService,
    name: str = "node-a",
    role: str = "runner",
    address: str | None = None,
) -> None:
    ports = {"node-a": "10.0.0.5", "node-b": "10.0.0.6", "builder-1": "10.0.0.8"}
    asyncio.run(
        service.heartbeat(
            NodeReport(name, address or f"{ports[name]}:50051", role),  # pyright: ignore[reportArgumentType]
            NODE_TOKENS[name],
        )
    )


def test_a_node_is_ready_for_15_seconds_after_its_last_heartbeat_then_unhealthy(
    node_service: NodeService, clock: FakeClock
):
    _beat(node_service)

    clock.advance(15)
    assert asyncio.run(node_service.statuses()) == {"node-a": "ready"}
    clock.advance(0.5)
    assert asyncio.run(node_service.statuses()) == {"node-a": "unhealthy"}

    _beat(node_service)
    assert asyncio.run(node_service.statuses()) == {"node-a": "ready"}


def test_the_threshold_is_a_setting(
    nodes_uow: InMemoryNodesUoW, settings: Settings, clock: FakeClock
):
    service = NodeService(
        lambda: nodes_uow, settings.model_copy(update={"node_ttl_seconds": 2}), clock=clock
    )
    _beat(service)

    clock.advance(3)

    assert asyncio.run(service.statuses()) == {"node-a": "unhealthy"}


# GET /nodes


def test_nodes_need_a_login(anon_client: TestClient):
    assert anon_client.get("/nodes").status_code == 401


def test_nodes_list_status_last_seen_and_replica_count_without_addresses(
    client: TestClient,
    node_service: NodeService,
    clock: FakeClock,
    deploys_uow,
):
    _beat(node_service, "node-a")
    clock.advance(20)
    _beat(node_service, "node-b")
    client.post(
        "/apps",
        json={"name": "blog", "preset": "fastapi", "repo_url": "https://github.com/e/b.git"},
    )
    asyncio.run(
        add_running_deploy(deploys_uow, "d1", "blog", [("node-a", 1), ("node-a", 2), ("node-b", 3)])
    )

    resp = client.get("/nodes")

    assert resp.status_code == 200
    by_name = {n["name"]: n for n in resp.json()}
    assert by_name["node-a"]["status"] == "unhealthy"
    assert by_name["node-b"]["status"] == "ready"
    assert (by_name["node-a"]["replicas"], by_name["node-b"]["replicas"]) == (2, 1)
    assert by_name["node-a"]["role"] == "runner"
    assert by_name["node-a"]["last_seen_at"].startswith("2026-10-18T12:00:00")
    for field in ("address", "token"):
        assert field not in by_name["node-a"]
    assert "10.0.0.5" not in resp.text


# directory


def test_without_registered_nodes_the_static_configuration_is_used(
    node_service: NodeService,
):
    runners = asyncio.run(node_service.runners())

    assert [(r.name, r.address, r.ready) for r in runners] == [
        ("node-a", "10.0.0.5:50051", True)
    ]
    assert asyncio.run(node_service.builder_address()) == "builder:50051"
    assert asyncio.run(node_service.runner_address("node-a")) == "10.0.0.5:50051"
    assert asyncio.run(node_service.runner_address("nope")) is None


def test_registered_runners_replace_the_static_ones(node_service: NodeService):
    _beat(node_service, "node-b", address="10.0.0.60:50051")

    runners = asyncio.run(node_service.runners())

    assert [(r.name, r.address) for r in runners] == [("node-b", "10.0.0.60:50051")]
    assert asyncio.run(node_service.runner_address("node-a")) is None
    # No builder has registered: the static one still serves.
    assert asyncio.run(node_service.builder_address()) == "builder:50051"


def test_a_registered_builder_replaces_the_static_one(
    node_service: NodeService, clock: FakeClock
):
    _beat(node_service, "builder-1", role="builder")

    assert asyncio.run(node_service.builder_address()) == "10.0.0.8:50051"

    clock.advance(16)  # registered but silent: no builder, not a fall back to the static one
    assert asyncio.run(node_service.builder_address()) is None


def test_an_unhealthy_runner_stays_known_but_not_ready(
    node_service: NodeService, clock: FakeClock
):
    _beat(node_service, "node-a")
    _beat(node_service, "node-b")
    clock.advance(10)
    _beat(node_service, "node-b")
    clock.advance(6)

    runners = {r.name: r for r in asyncio.run(node_service.runners())}

    assert (runners["node-a"].ready, runners["node-b"].ready) == (False, True)
    # RemoveReplica on a node that went quiet is still tried.
    assert asyncio.run(node_service.runner_address("node-a")) == "10.0.0.5:50051"


def test_a_node_with_both_roles_serves_as_builder_and_runner(node_service: NodeService):
    _beat(node_service, "node-a", role="both")

    assert asyncio.run(node_service.builder_address()) == "10.0.0.5:50051"
    assert asyncio.run(node_service.runner_names()) == ["node-a"]


def test_the_address_cache_is_short_lived_and_dropped_by_a_heartbeat(
    nodes_uow: InMemoryNodesUoW, settings: Settings, clock: FakeClock
):
    now = [0.0]
    service = NodeService(
        lambda: nodes_uow, settings, clock=clock, monotonic=lambda: now[0], cache_ttl=1.0
    )
    _beat(service)
    assert asyncio.run(service.runner_address("node-a")) == "10.0.0.5:50051"

    # Written behind the service's back: the cached copy is served until it expires...
    from app.nodes.repositories.nodes import Node

    asyncio.run(
        nodes_uow.nodes.upsert(Node("node-a", "10.9.9.9:50051", "runner", clock.now))
    )
    assert asyncio.run(service.runner_address("node-a")) == "10.0.0.5:50051"
    now[0] += 1.5
    assert asyncio.run(service.runner_address("node-a")) == "10.9.9.9:50051"

    # ...but a heartbeat through the service takes effect at once.
    _beat(service, address="10.0.0.7:50051")
    assert asyncio.run(service.runner_address("node-a")) == "10.0.0.7:50051"


def test_a_node_silent_for_60_seconds_is_dead_and_only_then(
    node_service: NodeService, clock: FakeClock
):
    _beat(node_service)

    clock.advance(60)
    [node] = asyncio.run(node_service.views())
    assert node.status == "unhealthy"
    clock.advance(0.5)
    [node] = asyncio.run(node_service.views())
    assert node.status == "dead"
    [runner] = asyncio.run(node_service.runners())
    assert (runner.ready, runner.dead) == (False, True)
    # the routing monitor only distinguishes ready from not ready
    assert asyncio.run(node_service.statuses()) == {"node-a": "unhealthy"}
