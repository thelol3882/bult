"""Subscribers of other domains' events (wired in main.create_app); see docs/architecture/deploy-saga.md."""

import logging

from app.agents.client import Agents
from app.apps.events import AppDeleted
from app.deploys.repositories.deploys import DeployRepository
from app.ingress.routes import RouteApplyError, RouteWriter, running_routes

logger = logging.getLogger(__name__)


async def on_app_deleted(
    event: AppDeleted,
    *,
    repo: DeployRepository,
    agents: Agents,
    routes: RouteWriter,
    runner_addrs: dict[str, str],
) -> None:
    """Forget the app's deploys, drop its routes, remove its replicas.

    Outside-world failures are logged, not raised (the app is already gone).
    """
    gone = [d for d in repo.list_all() if d.app_name == event.name]
    repo.delete_for_app(event.name)

    # Routes first: stop sending traffic, then remove the replicas.
    # Always re-applied: a deploy in flight may have published this app's route already.
    gen: int | None = None
    async with routes.lock:
        desired = running_routes(repo.list_all(), runner_addrs)
        try:
            gen = routes.apply(desired)
            await routes.wait_applied(gen)
        except (RouteApplyError, TimeoutError) as e:
            logger.warning("delete %s: route update failed: %r", event.name, e)

    removed = 0
    for deploy in gone:
        if deploy.status != "running" or not deploy.node:
            continue
        replica_id = f"{deploy.id}-r0"
        try:
            await agents.remove_replica(node=deploy.node, replica_id=replica_id)
            removed += 1
        except Exception:
            logger.warning(
                "delete %s: could not remove replica %s on %s",
                event.name,
                replica_id,
                deploy.node,
                exc_info=True,
            )

    logger.info(
        "app %s deleted: %d deploys, %d replicas removed, route generation %s",
        event.name,
        len(gone),
        removed,
        gen if gen is not None else "-",
    )
