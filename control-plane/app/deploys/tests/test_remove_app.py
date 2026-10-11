"""DeployService.remove_app and the AppDeleted handler (thin delegation)."""

import asyncio
from typing import cast

from app.apps.events import AppDeleted
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.deploys.handlers import on_app_deleted
from app.deploys.repositories.deploys import Deploy, InMemoryDeployRepository
from app.deploys.services.deploys import DeployService
from app.ingress.routes import Route
from tests.fakes import FakeAgentClients, FakeRoutes


def _running(deploy_id: str, app_name: str, port: int) -> Deploy:
    return Deploy(
        id=deploy_id, app_name=app_name, status="running", node="node-a", host_port=port
    )


def _service(
    repo: InMemoryDeployRepository,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    settings: Settings,
) -> DeployService:
    # apps is unused by remove_app.
    return DeployService(
        repo, cast(AppsFacade, None), agents, routes, settings, set()
    )


def test_remove_app_drops_deploys_reapplies_routes_and_removes_replica(
    deploy_repo: InMemoryDeployRepository,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    settings: Settings,
):
    deploy_repo.add(_running("d-blog", "blog", 30001))
    deploy_repo.add(_running("d-shop", "shop", 30002))

    asyncio.run(_service(deploy_repo, agents, routes, settings).remove_app("blog"))

    assert deploy_repo.get("d-blog") is None
    assert deploy_repo.get("d-shop") is not None
    assert routes.applied[-1] == [Route("shop", "10.0.0.5", 30002)]
    assert agents.remove_calls == [{"node": "node-a", "replica_id": "d-blog-r0"}]


def test_handler_delegates_to_remove_app():
    calls: list[str] = []

    class Spy:
        async def remove_app(self, app_name: str) -> None:
            calls.append(app_name)

    asyncio.run(on_app_deleted(AppDeleted(name="blog"), cast(DeployService, Spy())))

    assert calls == ["blog"]
