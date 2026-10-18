"""N replicas: placement across nodes, partial success, blue-green and resume with several."""

import asyncio

import grpc

from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route, Upstream
from tests.fakes import (
    HOST_PORT,
    IMAGE_DIGEST,
    IMAGE_REPOSITORY,
    NODE_B,
    FakeAgentClients,
    FakeNodes,
    FakeRoutes,
    add_running_deploy,
    make_worker,
    rpc_error,
    run_deploys,
)

IMAGE = f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"


def _two_nodes() -> tuple[FakeNodes, FakeAgentClients]:
    nodes = FakeNodes()
    nodes.add(*NODE_B)
    return nodes, FakeAgentClients(nodes=nodes)


def _starting(deploy_id: str = "d1", desired: int = 3) -> Deploy:
    return Deploy(
        id=deploy_id,
        app_name="blog",
        status="starting",
        image=IMAGE,
        desired_replicas=desired,
    )


def _run(uow, agents, routes, **kw) -> None:
    asyncio.run(run_deploys(make_worker(uow, agents, routes, **kw)))


def _get(uow: InMemoryDeploysUoW, deploy_id: str) -> Deploy:
    deploy = asyncio.run(uow.deploys.get(deploy_id))
    assert deploy is not None
    return deploy


def _placement(uow: InMemoryDeploysUoW, deploy_id: str) -> dict[str, int]:
    rows = asyncio.run(uow.replicas.list_running([deploy_id]))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.node] = counts.get(r.node, 0) + 1
    return counts


def test_three_replicas_spread_over_two_nodes_two_and_one(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    asyncio.run(deploys_uow.deploys.add(_starting()))

    _run(deploys_uow, agents, routes)

    assert _get(deploys_uow, "d1").status == "running"
    assert _placement(deploys_uow, "d1") == {"node-a": 2, "node-b": 1}
    assert [c["replica_id"] for c in agents.run_calls] == ["d1-r0", "d1-r1", "d1-r2"]
    [route] = routes.applied[-1]
    assert route.name == "blog" and len(route.upstreams) == 3
    assert {u.node_ip for u in route.upstreams} == {"10.0.0.5", "10.0.0.6"}


def test_an_unhealthy_node_gets_no_replicas(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    nodes.set_ready("node-b", False)
    asyncio.run(deploys_uow.deploys.add(_starting(desired=2)))

    _run(deploys_uow, agents, routes)

    assert _placement(deploys_uow, "d1") == {"node-a": 2}
    assert {c["node"] for c in agents.run_calls} == {"node-a"}


def test_a_replica_that_fails_on_one_node_is_placed_on_another(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    agents.run_errors["node-a"] = rpc_error(grpc.StatusCode.UNAVAILABLE)
    asyncio.run(deploys_uow.deploys.add(_starting(desired=2)))

    _run(deploys_uow, agents, routes)

    assert _get(deploys_uow, "d1").status == "running"
    assert _placement(deploys_uow, "d1") == {"node-b": 2}


def test_partial_success_is_running_with_fewer_replicas_and_keeps_the_ones_that_started(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    agents.fail_replica_ids = {"d1-r2"}
    asyncio.run(deploys_uow.deploys.add(_starting()))

    _run(deploys_uow, agents, routes)

    deploy = _get(deploys_uow, "d1")
    assert deploy.status == "running"
    assert deploy.desired_replicas == 3
    assert len(asyncio.run(deploys_uow.replicas.list_running(["d1"]))) == 2
    assert agents.remove_calls == []  # the two that came up are not rolled back
    [route] = routes.applied[-1]
    assert len(route.upstreams) == 2


def test_all_replicas_failing_fails_the_deploy_and_leaves_no_route(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    agents.run_error = rpc_error(grpc.StatusCode.UNAVAILABLE)
    asyncio.run(deploys_uow.deploys.add(_starting()))

    _run(deploys_uow, agents, routes)

    deploy = _get(deploys_uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "start failed: node is unreachable"
    assert asyncio.run(deploys_uow.replicas.list_all_running()) == []
    assert routes.applied == []


def test_no_ready_node_fails_the_deploy_with_a_clear_message(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    nodes.set_ready("node-a", False)
    nodes.set_ready("node-b", False)
    asyncio.run(deploys_uow.deploys.add(_starting(desired=2)))

    _run(deploys_uow, agents, routes)

    deploy = _get(deploys_uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "start failed: no node is available"
    assert agents.run_calls == []


def test_replicas_on_nodes_that_are_not_ready_when_routing_fail_the_deploy_and_are_removed(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()

    async def node_dies_after_start() -> None:
        nodes.set_ready("node-a", False)
        nodes.set_ready("node-b", False)

    agents.on_run = node_dies_after_start
    asyncio.run(deploys_uow.deploys.add(_starting(desired=1)))

    _run(deploys_uow, agents, routes)

    assert _get(deploys_uow, "d1").status == "failed"
    assert [c["replica_id"] for c in agents.remove_calls] == ["d1-r0"]
    assert asyncio.run(deploys_uow.replicas.list_all_running()) == []


def test_route_failure_removes_every_replica_of_the_deploy(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes, monkeypatch
):
    nodes, agents = _two_nodes()

    async def rejected(generation: int, timeout: float = 10.0) -> None:
        from app.ingress.routes import RouteApplyError

        raise RouteApplyError("nginx -t failed")

    monkeypatch.setattr(routes, "wait_applied", rejected)
    asyncio.run(deploys_uow.deploys.add(_starting()))

    _run(deploys_uow, agents, routes)

    assert _get(deploys_uow, "d1").status == "failed"
    assert sorted(c["replica_id"] for c in agents.remove_calls) == [
        "d1-r0",
        "d1-r1",
        "d1-r2",
    ]
    assert agents.replicas == {"node-a": {}, "node-b": {}}
    assert asyncio.run(deploys_uow.replicas.list_all_running()) == []


def test_resume_reuses_the_replicas_that_exist_and_starts_only_the_missing_one(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    asyncio.run(deploys_uow.deploys.add(_starting()))
    agents.seed_replica("d1-r0", "blog", node="node-b", port=40000)
    agents.seed_replica("d1-r1", "blog", node="node-a", port=40001)

    _run(deploys_uow, agents, routes)

    assert [c["replica_id"] for c in agents.run_calls] == ["d1-r2"]
    assert _get(deploys_uow, "d1").status == "running"
    rows = asyncio.run(deploys_uow.replicas.list_running(["d1"]))
    assert [(r.index, r.node, r.host_port) for r in rows[:2]] == [
        (0, "node-b", 40000),
        (1, "node-a", 40001),
    ]
    # The new replica fills the gap: node-a and node-b have one each, so node-a (name) wins.
    assert agents.run_calls[0]["node"] == "node-a"


def test_a_redeploy_with_replicas_switches_the_route_then_retires_all_the_old_ones(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes, monkeypatch
):
    nodes, agents = _two_nodes()
    order: list[str] = []
    apply, remove = routes.apply, agents.remove_replica

    def traced_apply(*args, **kwargs) -> int:
        order.append("route")
        return apply(*args, **kwargs)

    async def traced_remove(node: str, replica_id: str) -> None:
        order.append(f"remove {replica_id}")
        await remove(node, replica_id)

    monkeypatch.setattr(routes, "apply", traced_apply)
    monkeypatch.setattr(agents, "remove_replica", traced_remove)

    async def scenario() -> None:
        await add_running_deploy(
            deploys_uow, "old", "blog", [("node-a", 30001), ("node-b", 30002)], image=IMAGE
        )
        agents.seed_replica("old-r0", "blog", node="node-a", port=30001)
        agents.seed_replica("old-r1", "blog", node="node-b", port=30002)
        await deploys_uow.deploys.add(
            Deploy(id="new", app_name="blog", desired_replicas=3)
        )
        agents.build_states = ["SUCCEEDED"]
        await run_deploys(make_worker(deploys_uow, agents, routes))

    asyncio.run(scenario())

    assert _get(deploys_uow, "new").status == "running"
    assert _get(deploys_uow, "old").status == "superseded"
    assert order == ["route", "remove old-r0", "remove old-r1"]
    [route] = routes.applied[-1]
    assert {u.host_port for u in route.upstreams}.isdisjoint({30001, 30002})
    assert len(route.upstreams) == 3
    assert sorted(r for node in agents.replicas.values() for r in node) == [
        "new-r0",
        "new-r1",
        "new-r2",
    ]
    assert [r.id for r in asyncio.run(deploys_uow.replicas.list_all_running())] == [
        "new-r0",
        "new-r1",
        "new-r2",
    ]


def test_old_replicas_do_not_pull_the_new_ones_off_their_nodes(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    """The placement of a redeploy counts only its own replicas."""
    nodes, agents = _two_nodes()

    async def scenario() -> None:
        await add_running_deploy(
            deploys_uow, "old", "blog", [("node-a", 30001), ("node-a", 30002)], image=IMAGE
        )
        await deploys_uow.deploys.add(
            Deploy(id="new", app_name="blog", status="starting", image=IMAGE, desired_replicas=2)
        )
        await run_deploys(make_worker(deploys_uow, agents, routes))

    asyncio.run(scenario())

    # node-a carries the old pair, but within "new" the nodes start even: one each
    assert _placement(deploys_uow, "new") == {"node-a": 1, "node-b": 1}


def test_route_upstreams_are_the_replicas_of_the_latest_running_deploy_only(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    nodes, agents = _two_nodes()
    asyncio.run(deploys_uow.deploys.add(_starting(desired=2)))

    _run(deploys_uow, agents, routes)

    [route] = routes.applied[-1]
    assert route == Route(
        "blog", (Upstream("10.0.0.5", HOST_PORT), Upstream("10.0.0.6", HOST_PORT + 1))
    )
