"""Startup check: a `running` deploy whose replica is gone is marked failed;
a replica whose deploy is not running (and not in flight) is removed.
"""

import logging
from collections.abc import Callable

from app.agents.client import Agents
from app.apps.services.facade import AppsFacade
from app.deploys.repositories.deploys import ACTIVE_STATUSES
from app.deploys.services.routing import stopped_apps
from app.deploys.services.runner import list_replicas_by_node, remove_replica_quietly
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteApplyError, RouteWriter, running_routes

logger = logging.getLogger(__name__)


async def fail_deploys_without_replica(
    agents: Agents,
    uow_factory: Callable[[], DeploysUoW],
    routes: RouteWriter,
    runner_addrs: dict[str, str],
    apps: AppsFacade,
) -> list[str]:
    """Mark running deploys whose replica no reachable runner has as failed; re-apply the routes.

    A deploy on a node that did not answer is left alone: we cannot tell.
    Returns the ids of the deploys marked failed.
    """
    by_node, unreachable = await list_replicas_by_node(agents)
    present = {r.replica_id for replicas in by_node.values() for r in replicas}

    async with uow_factory() as uow:
        running = [d for d in await uow.deploys.list_all() if d.status == "running"]
    gone = [
        d
        for d in running
        if f"{d.id}-r0" not in present and d.node not in unreachable
    ]

    for deploy in gone:
        async with uow_factory() as uow:
            changed = await uow.deploys.update(
                deploy.id, status="failed", error="replica is gone"
            )
            if changed is not None:
                await uow.commit()
        logger.warning(
            "deploy %s: replica %s-r0 is gone from %s, marked failed",
            deploy.id,
            deploy.id,
            deploy.node,
        )

    # Always re-applied: the sidecar's routes may predate a wiped node or database.
    async with routes.lock:
        async with uow_factory() as uow:
            deploys = await uow.deploys.list_all()
        try:
            desired = running_routes(deploys, runner_addrs)
            gen = routes.apply(desired, await stopped_apps(apps, desired))
            await routes.wait_applied(gen)
        except (RouteApplyError, TimeoutError) as e:
            logger.warning("startup check: route update failed: %r", e)

    return [d.id for d in gone]


async def remove_orphan_replicas(
    agents: Agents, uow_factory: Callable[[], DeploysUoW]
) -> list[tuple[str, str]]:
    """Garbage collection: remove replicas whose deploy is not `running`, or has no row.

    The replicas of deploys still in flight are left alone (a resumed deploy reuses them).
    A node that does not answer is skipped. Returns (node, replica_id) of what was removed.
    """
    by_node, _ = await list_replicas_by_node(agents)
    async with uow_factory() as uow:
        status = {d.id: d.status for d in await uow.deploys.list_all()}

    removed: list[tuple[str, str]] = []
    for node, replicas in by_node.items():
        for replica in replicas:
            deploy_id, sep, _ = replica.replica_id.rpartition("-r")
            if not sep:
                continue  # not a name we create
            if status.get(deploy_id) in ("running", *ACTIVE_STATUSES):
                continue
            logger.warning(
                "replica %s on %s has no running deploy (%s), removing",
                replica.replica_id,
                node,
                status.get(deploy_id, "no row"),
            )
            if await remove_replica_quietly(agents, node, replica.replica_id):
                removed.append((node, replica.replica_id))
    return removed
