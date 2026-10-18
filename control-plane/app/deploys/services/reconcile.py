"""Startup check: a `running` deploy whose replicas are all gone is marked failed;
a replica that its deploy no longer lists is removed.
"""

import logging
from collections.abc import Callable

from app.agents.client import Agents
from app.apps.services.facade import AppsFacade
from app.deploys.repositories.deploys import ACTIVE_STATUSES
from app.deploys.repositories.replicas import replica_id
from app.deploys.services.routing import current_routes, stopped_apps
from app.deploys.services.runner import list_replicas_by_node, remove_replica_quietly
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteApplyError, RouteWriter
from app.nodes.services.facade import NodesFacade

logger = logging.getLogger(__name__)


async def fail_deploys_without_replica(
    agents: Agents,
    uow_factory: Callable[[], DeploysUoW],
    routes: RouteWriter,
    nodes: NodesFacade,
    apps: AppsFacade,
) -> list[str]:
    """Retire the replica rows no reachable runner has, mark running deploys left with none
    as failed, and re-apply the routes.

    A replica on a node that did not answer is left alone: we cannot tell.
    Returns the ids of the deploys marked failed.
    """
    by_node, unreachable = await list_replicas_by_node(agents)
    present = {r.replica_id for replicas in by_node.values() for r in replicas}

    failed: list[str] = []
    async with uow_factory() as uow:
        running = [d for d in await uow.deploys.list_all() if d.status == "running"]
        rows = await uow.replicas.list_running(d.id for d in running)

    gone_rows = [r for r in rows if r.id not in present and r.node not in unreachable]
    gone_ids = {r.id for r in gone_rows}
    if gone_rows:
        async with uow_factory() as uow:
            await uow.replicas.mark_removed(gone_ids)
            await uow.commit()
        for r in gone_rows:
            logger.warning("replica %s is gone from %s", r.id, r.node)

    survivors = {r.deploy_id for r in rows if r.id not in gone_ids}
    for deploy in running:
        if deploy.id in survivors:
            continue
        async with uow_factory() as uow:
            changed = await uow.deploys.update(
                deploy.id, status="failed", error="replica is gone"
            )
            if changed is not None:
                await uow.commit()
        failed.append(deploy.id)
        logger.warning("deploy %s: no replica left, marked failed", deploy.id)

    # Always re-applied: the sidecar's routes may predate a wiped node or database.
    # Node health is not judged here: nodes that have not reported yet look unhealthy,
    # and the node monitor corrects the routes once it has seen them.
    async with routes.lock:
        async with uow_factory() as uow:
            desired = await current_routes(uow, nodes, ignore_health=True)
        try:
            gen = routes.apply(desired, await stopped_apps(apps, desired))
            await routes.wait_applied(gen)
        except (RouteApplyError, TimeoutError) as e:
            logger.warning("startup check: route update failed: %r", e)

    return failed


async def remove_orphan_replicas(
    agents: Agents, uow_factory: Callable[[], DeploysUoW]
) -> list[tuple[str, str]]:
    """Garbage collection: remove replicas that no live deploy lists.

    Kept: the replicas a running deploy lists, and every replica of a deploy still in flight
    (`queued`, `building`, `starting`; a resumed deploy reuses them). Everything else goes:
    replicas of finished or deleted deploys, and extras of a running deploy (a scale-down
    whose removal failed). A node that does not answer is skipped. Returns (node, replica_id)
    of what was removed.
    """
    by_node, _ = await list_replicas_by_node(agents)
    async with uow_factory() as uow:
        status = {d.id: d.status for d in await uow.deploys.list_all()}
        listed = {r.id for r in await uow.replicas.list_all_running()}

    removed: list[tuple[str, str]] = []
    for node, replicas in by_node.items():
        for replica in replicas:
            deploy_id, sep, index = replica.replica_id.rpartition("-r")
            if not sep or not index.isdigit() or replica.replica_id != replica_id(deploy_id, int(index)):
                continue  # not a name we create
            state = status.get(deploy_id)
            if state in ACTIVE_STATUSES or (
                state == "running" and replica.replica_id in listed
            ):
                continue
            logger.warning(
                "replica %s on %s has no live deploy (%s), removing",
                replica.replica_id,
                node,
                state or "no row",
            )
            if await remove_replica_quietly(agents, node, replica.replica_id):
                removed.append((node, replica.replica_id))
    return removed
