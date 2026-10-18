"""Which routes the ingress should have: from the database and the nodes' health."""

from app.apps.services.facade import AppsFacade
from app.deploys.uow import DeploysUoW
from app.ingress.routes import Route, node_ip, running_routes
from app.nodes.services.facade import NodesFacade


async def node_maps(nodes: NodesFacade) -> tuple[dict[str, str], set[str]]:
    """({node name: its IP}, names of the ready nodes), for every known runner."""
    runners = await nodes.runners()
    return (
        {r.name: node_ip(r.address) for r in runners},
        {r.name for r in runners if r.ready},
    )


async def current_routes(
    uow: DeploysUoW,
    nodes: NodesFacade,
    skip_app: str | None = None,
    ignore_health: bool = False,
) -> list[Route]:
    """The routes the database asks for: running deploys on ready nodes
    (`ignore_health`: on every known node)."""
    deploys = await uow.deploys.list_all()
    replicas = await uow.replicas.list_all_running()
    node_ips, routable = await node_maps(nodes)
    if ignore_health:
        routable = set(node_ips)
    return running_routes(deploys, replicas, node_ips, routable, skip_app=skip_app)


async def stopped_apps(
    apps: AppsFacade, routes: list[Route], skip_app: str | None = None
) -> list[str]:
    """Stopped apps that have no route: a running deploy wins over the flag."""
    live = {r.name for r in routes}
    return [
        name
        for name in await apps.stopped_app_names()
        if name not in live and name != skip_app
    ]
