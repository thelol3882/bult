"""DeployService.remove_app and the AppDeleted handler (thin delegation)."""

import asyncio
from typing import cast

from app.apps.events import AppDeleted
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.deploys.handlers import on_app_deleted
from app.deploys.services.deploys import DeployService
from app.deploys.uow import InMemoryDeploysUoW
from app.nodes.services.facade import NodesFacade
from tests.fakes import (
    FakeAgentClients,
    FakeApps,
    FakeRoutes,
    add_running_deploy,
    one_route,
)


def _service(
    uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    settings: Settings,
) -> DeployService:
    return DeployService(
        lambda: uow,
        cast(AppsFacade, FakeApps()),
        agents,
        cast(NodesFacade, agents.nodes),
        routes,
        settings,
    )


def test_remove_app_drops_deploys_reapplies_routes_and_removes_replica(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    settings: Settings,
):
    async def scenario() -> None:
        await add_running_deploy(deploys_uow, "d-blog", "blog", [("node-a", 30001)])
        await add_running_deploy(deploys_uow, "d-shop", "shop", [("node-a", 30002)])
        agents.seed_replica("d-blog-r0", "blog")
        agents.seed_replica("d-shop-r0", "shop")
        await _service(deploys_uow, agents, routes, settings).remove_app("blog")
        assert await deploys_uow.deploys.get("d-blog") is None
        assert await deploys_uow.deploys.get("d-shop") is not None

    asyncio.run(scenario())
    assert (
        deploys_uow.commits == 1
    )  # the delete is committed before routes/replicas are touched
    assert routes.applied[-1] == [one_route("shop", "10.0.0.5", 30002)]
    assert agents.remove_calls == [{"node": "node-a", "replica_id": "d-blog-r0"}]


def test_handler_delegates_to_remove_app():
    calls: list[str] = []

    class Spy:
        async def remove_app(self, app_name: str) -> None:
            calls.append(app_name)

    asyncio.run(on_app_deleted(AppDeleted(name="blog"), cast(DeployService, Spy())))

    assert calls == ["blog"]
