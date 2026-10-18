"""Node health decides which replicas are in the upstream; the startup check with several replicas."""

import asyncio
from typing import cast

from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.deploys.services.deploys import DeployService
from app.deploys.services.reconcile import (
    fail_deploys_without_replica,
    remove_orphan_replicas,
)
from app.deploys.uow import InMemoryDeploysUoW
from app.nodes.services.facade import NodesFacade
from app.nodes.services.monitor import NodeMonitor
from app.nodes.services.nodes import NodeReport, NodeService
from tests.fakes import (
    NODE_B,
    NODE_TOKENS,
    FakeAgentClients,
    FakeApps,
    FakeClock,
    FakeNodes,
    FakeRoutes,
    add_running_deploy,
)


def _service(
    uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    nodes: object,
    routes: FakeRoutes,
    settings: Settings,
) -> DeployService:
    return DeployService(
        lambda: uow,
        cast(AppsFacade, FakeApps()),
        agents,
        cast(NodesFacade, nodes),
        routes,
        settings,
    )


def _ports(routes: FakeRoutes) -> list[int]:
    [route] = routes.applied[-1]
    return sorted(u.host_port for u in route.upstreams)


def test_an_unhealthy_node_leaves_the_upstream_and_returns_when_it_is_ready_again(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    settings: Settings,
    node_service: NodeService,
    clock: FakeClock,
):
    """Real nodes service + monitor + route generation, as main wires them."""

    def beat(name: str, address: str) -> None:
        asyncio.run(
            node_service.heartbeat(NodeReport(name, address, "runner"), NODE_TOKENS[name])
        )

    facade = NodesFacade(node_service)
    service = _service(deploys_uow, agents, facade, routes, settings)
    monitor = NodeMonitor(
        node_service, lambda: _reapply(service), interval=3
    )

    async def _reapply(svc: DeployService) -> None:
        await svc.reapply_routes("node status change")

    beat("node-a", "10.0.0.5:50051")
    beat("node-b", "10.0.0.6:50051")
    asyncio.run(
        add_running_deploy(
            deploys_uow, "d1", "blog", [("node-a", 30001), ("node-b", 30002), ("node-a", 30003)]
        )
    )
    assert asyncio.run(monitor.check()) is False  # baseline

    clock.advance(10)
    beat("node-a", "10.0.0.5:50051")
    clock.advance(6)  # node-b has been silent for 16 s
    assert asyncio.run(monitor.check()) is True

    assert _ports(routes) == [30001, 30003]
    assert deploys_uow.replicas is not None
    assert len(asyncio.run(deploys_uow.replicas.list_running(["d1"]))) == 3  # not moved

    beat("node-b", "10.0.0.6:50051")
    assert asyncio.run(monitor.check()) is True
    assert _ports(routes) == [30001, 30002, 30003]


def test_an_app_whose_replicas_are_all_on_unhealthy_nodes_leaves_the_routes(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    settings: Settings,
    nodes: FakeNodes,
):
    nodes.add(*NODE_B)
    service = _service(deploys_uow, agents, nodes, routes, settings)

    async def scenario() -> None:
        await add_running_deploy(deploys_uow, "d1", "blog", [("node-a", 30001)])
        await add_running_deploy(deploys_uow, "d2", "shop", [("node-b", 30002)])
        nodes.set_ready("node-a", False)
        await service.reapply_routes("test")

    asyncio.run(scenario())

    assert [r.name for r in routes.applied[-1]] == ["shop"]
    # An unreachable app is not the same as a stopped one: no "stopped" page for it.
    assert routes.applied_stopped[-1] == []


# startup check


def test_startup_check_keeps_a_deploy_with_one_replica_left_and_removes_the_gone_row(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    nodes: FakeNodes,
):
    nodes.add(*NODE_B)

    async def scenario() -> list[str]:
        await add_running_deploy(
            deploys_uow, "d1", "blog", [("node-a", 30001), ("node-b", 30002)]
        )
        agents.seed_replica("d1-r1", "blog", node="node-b", port=30002)  # r0 vanished
        return await fail_deploys_without_replica(
            agents,
            lambda: deploys_uow,
            routes,
            cast(NodesFacade, nodes),
            cast(AppsFacade, FakeApps()),
        )

    assert asyncio.run(scenario()) == []
    deploy = asyncio.run(deploys_uow.deploys.get("d1"))
    assert deploy is not None and deploy.status == "running"
    assert [r.id for r in asyncio.run(deploys_uow.replicas.list_running(["d1"]))] == ["d1-r1"]
    assert _ports(routes) == [30002]


def test_startup_check_fails_a_deploy_when_every_replica_is_gone(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    nodes: FakeNodes,
):
    async def scenario() -> list[str]:
        await add_running_deploy(deploys_uow, "d1", "blog", [("node-a", 30001), ("node-a", 30002)])
        return await fail_deploys_without_replica(
            agents,
            lambda: deploys_uow,
            routes,
            cast(NodesFacade, nodes),
            cast(AppsFacade, FakeApps()),
        )

    assert asyncio.run(scenario()) == ["d1"]
    assert routes.applied[-1] == []


def test_startup_check_puts_unhealthy_nodes_back_in_the_routes_for_now(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    nodes: FakeNodes,
):
    """Right after a start the agents have not reported yet; the monitor judges them later."""
    nodes.set_ready("node-a", False)

    async def scenario() -> None:
        await add_running_deploy(deploys_uow, "d1", "blog", [("node-a", 30001)])
        agents.seed_replica("d1-r0", "blog", port=30001)
        await fail_deploys_without_replica(
            agents,
            lambda: deploys_uow,
            routes,
            cast(NodesFacade, nodes),
            cast(AppsFacade, FakeApps()),
        )

    asyncio.run(scenario())

    assert _ports(routes) == [30001]


def test_garbage_collection_removes_a_replica_the_running_deploy_no_longer_lists(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    async def scenario() -> list[tuple[str, str]]:
        await add_running_deploy(deploys_uow, "d1", "blog", [("node-a", 30001)])
        agents.seed_replica("d1-r0", "blog", port=30001)
        agents.seed_replica("d1-r1", "blog", port=30002)  # a scale-down whose removal failed
        return await remove_orphan_replicas(agents, lambda: deploys_uow)

    assert asyncio.run(scenario()) == [("node-a", "d1-r1")]
    assert list(agents.replicas["node-a"]) == ["d1-r0"]
