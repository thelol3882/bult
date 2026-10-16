"""Startup check: a `running` deploy whose replica is gone cannot serve; mark it failed."""

import logging
from collections.abc import Callable

from app.agents.client import Agents
from app.deploys.services.runner import list_replicas_by_node
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteApplyError, RouteWriter, running_routes

logger = logging.getLogger(__name__)


async def fail_deploys_without_replica(
    agents: Agents,
    uow_factory: Callable[[], DeploysUoW],
    routes: RouteWriter,
    runner_addrs: dict[str, str],
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
            gen = routes.apply(running_routes(deploys, runner_addrs))
            await routes.wait_applied(gen)
        except (RouteApplyError, TimeoutError) as e:
            logger.warning("startup check: route update failed: %r", e)

    return [d.id for d in gone]
