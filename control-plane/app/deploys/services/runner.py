"""Background part of a deploy: wait for the build, run a replica, publish the route."""

import asyncio
import logging

import grpc

from app.agents.client import Agents, DeployResult, ReplicaResult
from app.deploys.repositories.deploys import DeployRepository
from app.deploys.services.scheduler import pick_runner
from app.ingress.routes import (
    Route,
    RouteApplyError,
    RouteWriter,
    node_ip,
    running_routes,
)

logger = logging.getLogger(__name__)

CONTAINER_PORT = 8000  # PORT convention: the platform sets it
DEFAULT_CPU_MILLICORES = 500
DEFAULT_MEMORY_BYTES = 256 * 1024 * 1024

_FINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}
_RETRYABLE_POLL = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}
MAX_POLL_FAILURES = 5


# gRPC code -> user-facing reason; anything else is "internal error".
_USER_MESSAGES = {
    grpc.StatusCode.UNAVAILABLE: "node is unreachable",
    grpc.StatusCode.DEADLINE_EXCEEDED: "node did not answer in time",
    grpc.StatusCode.RESOURCE_EXHAUSTED: "not enough resources on the node",
    grpc.StatusCode.NOT_FOUND: "deploy is unknown to the builder",
}


async def run_deploy(
    agents: Agents,
    repo: DeployRepository,
    routes: RouteWriter,
    runner_addrs: dict[str, str],
    deploy_id: str,
    app_name: str,
    trusted_proxy: str,
    poll_interval: float = 1.5,
) -> None:
    """Drive one deploy to `running` or `failed`; never raises (except cancellation).

    trusted_proxy becomes FORWARDED_ALLOW_IPS; poll_interval is a parameter so tests don't sleep.
    """
    stage = "build"
    replica: ReplicaResult | None = None  # set once RunReplica succeeded, to compensate
    try:
        result = await _wait_for_build(agents, deploy_id, poll_interval)

        if result.state != "SUCCEEDED":
            if (
                repo.update(
                    deploy_id,
                    status="failed",
                    error=result.error or f"build {result.state.lower()}",
                )
                is None
            ):
                _log_cancelled(deploy_id)
            return

        image = f"{result.image_repository}@{result.image_digest}"
        if (
            repo.update(
                deploy_id,
                status="starting",
                commit_sha=result.commit_sha,
                image=image,
            )
            is None
        ):
            _log_cancelled(deploy_id)
            return

        stage = "start"
        node = pick_runner(agents.runner_names)
        replica = await agents.run_replica(
            node=node,
            replica_id=f"{deploy_id}-r0",
            app_id=app_name,
            image_repository=result.image_repository,
            image_digest=result.image_digest,
            container_port=CONTAINER_PORT,
            env={
                "PORT": str(CONTAINER_PORT),
                "FORWARDED_ALLOW_IPS": trusted_proxy,
            },
            cpu_millicores=DEFAULT_CPU_MILLICORES,
            memory_bytes=DEFAULT_MEMORY_BYTES,
        )

        stage = "route"
        this_route = Route(
            app_name, node_ip(runner_addrs[replica.node]), replica.host_port
        )
        compensate = False  # the route was not published: undo RunReplica below
        async with routes.lock:
            if repo.get(deploy_id) is None:
                # The app was deleted while the replica was starting: don't publish.
                _log_cancelled(deploy_id)
                compensate = True
            else:
                desired = running_routes(
                    repo.list_all(), runner_addrs, skip_app=app_name
                )
                desired.append(this_route)
                try:
                    gen = routes.apply(desired)
                    await routes.wait_applied(gen)
                except (RouteApplyError, TimeoutError) as e:
                    logger.warning("deploy %s: route failed: %r", deploy_id, e)
                    repo.update(
                        deploy_id,
                        status="failed",
                        error="route failed: could not publish the app's address",
                    )
                    compensate = True

        if compensate:
            # Outside the lock: a node RPC must not block other deploys.
            await _remove_replica(agents, replica)
            return

        if (
            repo.update(
                deploy_id,
                status="running",
                node=replica.node,
                host_port=replica.host_port,
            )
            is None
        ):
            # Deleted during wait_applied: the AppDeleted handler re-applies the routes after us.
            _log_cancelled(deploy_id)
            await _remove_replica(agents, replica)
            return
        logger.info(
            "deploy %s running on %s:%d", deploy_id, replica.node, replica.host_port
        )

    except grpc.aio.AioRpcError as e:
        logger.warning(
            "deploy %s: %s failed: %s %s", deploy_id, stage, e.code().name, e.details()
        )
        reason = _USER_MESSAGES.get(e.code(), "internal error")
        repo.update(deploy_id, status="failed", error=f"{stage} failed: {reason}")
        await _remove_replica(agents, replica)

    except Exception:
        logger.exception("deploy %s: unexpected error during %s", deploy_id, stage)
        repo.update(
            deploy_id, status="failed", error=f"{stage} failed: internal error"
        )
        await _remove_replica(agents, replica)


def _log_cancelled(deploy_id: str) -> None:
    logger.info("deploy %s: deploy cancelled (app deleted)", deploy_id)


async def _remove_replica(agents: Agents, replica: ReplicaResult | None) -> None:
    """Compensate RunReplica; best effort."""
    if replica is not None:
        _ = await remove_replica_quietly(agents, replica.node, replica.replica_id)


async def remove_replica_quietly(agents: Agents, node: str, replica_id: str) -> bool:
    """RemoveReplica, logging instead of raising; True if removed."""
    try:
        await agents.remove_replica(node=node, replica_id=replica_id)
    except Exception:
        logger.warning(
            "could not remove replica %s on %s", replica_id, node, exc_info=True
        )
        return False
    return True


async def _wait_for_build(
    agents: Agents, deploy_id: str, poll_interval: float
) -> DeployResult:
    """Poll GetDeploy until a final state, retrying short outages."""
    failures = 0
    while True:
        try:
            result = await agents.get_deploy(deploy_id)
        except grpc.aio.AioRpcError as e:
            if e.code() not in _RETRYABLE_POLL:
                raise
            failures += 1
            if failures >= MAX_POLL_FAILURES:
                raise
            logger.warning(
                "deploy %s: GetDeploy %s (%d/%d), retrying",
                deploy_id,
                e.code().name,
                failures,
                MAX_POLL_FAILURES,
            )
            await asyncio.sleep(min(poll_interval * 2**failures, 15))
            continue
        failures = 0
        if result.state in _FINAL_STATES:
            return result
        await asyncio.sleep(poll_interval)
