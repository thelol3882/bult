"""Deploy saga steps. Each step resumes from the deploy's status and is safe to repeat.

A worker holds a lease on the deploy; every status write is fenced by it (`update_owned`),
so a worker that lost the lease writes nothing more. Every write is its own short UoW;
gRPC calls, polling sleeps and route waits run outside any UoW.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import grpc

from app.agents.client import Agents, DeployResult, ReplicaInfo, ReplicaResult
from app.apps.services.facade import AppNotFoundError, AppsFacade
from app.deploys.repositories.deploys import Deploy
from app.deploys.services.routing import stopped_apps
from app.deploys.services.scheduler import pick_runner
from app.deploys.uow import DeploysUoW
from app.ingress.routes import (
    Route,
    RouteApplyError,
    RouteWriter,
    node_ip,
    running_routes,
)

logger = logging.getLogger(__name__)

PRESETS_DIR = Path(__file__).resolve().parents[3] / "presets"

CONTAINER_PORT = 8000  # PORT convention: the platform sets it
DEFAULT_CPU_MILLICORES = 500
DEFAULT_MEMORY_BYTES = 256 * 1024 * 1024

_FINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}
# A deploy written in one of these statuses is done with its worker: the lease goes with it.
_LEASE_ENDS_WITH = {"running", "failed", "superseded"}
_RETRYABLE_POLL = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}
MAX_POLL_FAILURES = 5


# gRPC code -> user-facing reason; anything else is "internal error".
_USER_MESSAGES = {
    grpc.StatusCode.UNAVAILABLE: "node is unreachable",
    grpc.StatusCode.DEADLINE_EXCEEDED: "node did not answer in time",
    grpc.StatusCode.RESOURCE_EXHAUSTED: "not enough resources on the node",
    grpc.StatusCode.NOT_FOUND: "deploy is unknown to the builder",
}


@dataclass(frozen=True)
class RunnerContext:
    """Everything the steps need; `owner` is the worker id holding the lease."""

    agents: Agents
    uow_factory: Callable[[], DeploysUoW]
    apps: AppsFacade
    routes: RouteWriter
    runner_addrs: dict[str, str]
    trusted_proxy: str
    owner: str
    poll_interval: float = 1.5  # a parameter so tests don't sleep
    max_attempts: int = 3


@lru_cache
def _dockerfile(preset: str) -> str:
    """Dockerfile text of a preset (cached)."""
    return (PRESETS_DIR / preset / "Dockerfile").read_text()


async def process_deploy(ctx: RunnerContext, deploy: Deploy) -> None:
    """Drive a claimed deploy to `running` or `failed`, or stop quietly when the lease is lost.

    Never raises (except cancellation and a database failure on a write).
    """
    stage = "build"
    replica: ReplicaResult | None = None  # set once we hold one, to compensate
    try:
        if deploy.attempts > ctx.max_attempts:
            await _write(
                ctx,
                deploy.id,
                status="failed",
                error=f"gave up after {ctx.max_attempts} attempts",
            )
            return

        current: Deploy | None = deploy
        if current.status == "queued":
            current = await _start_build(ctx, current)
        if current is not None and current.status == "building":
            current = await _await_build(ctx, current)
        if current is None or current.status != "starting":
            return

        stage = "start"
        replica = await _ensure_replica(ctx, current)
        stage = "route"
        await _publish_and_finish(ctx, current, replica)

    except AppNotFoundError:
        _log_cancelled(deploy.id)

    except grpc.aio.AioRpcError as e:
        logger.warning(
            "deploy %s: %s failed: %s %s",
            deploy.id,
            stage,
            e.code().name,
            e.details(),
        )
        reason = _USER_MESSAGES.get(e.code(), "internal error")
        await _fail(ctx, deploy.id, f"{stage} failed: {reason}", replica)

    except Exception:
        logger.exception("deploy %s: unexpected error during %s", deploy.id, stage)
        await _fail(ctx, deploy.id, f"{stage} failed: internal error", replica)


async def _start_build(ctx: RunnerContext, deploy: Deploy) -> Deploy | None:
    """queued -> building: StartDeploy (idempotent by deploy_id, so a retry is safe)."""
    try:
        app = await ctx.apps.get_app_unchecked(deploy.app_name)
    except AppNotFoundError:
        _log_cancelled(deploy.id)
        return None

    for attempt in (1, 2):
        try:
            _ = await ctx.agents.start_deploy(
                deploy_id=deploy.id,
                app_id=app.name,
                repo_url=app.repo_url,
                branch=app.branch,
                subdir=app.subdir,
                dockerfile=_dockerfile(app.preset),
            )
            break
        except grpc.aio.AioRpcError as e:
            code = e.code()
            if code == grpc.StatusCode.DEADLINE_EXCEEDED and attempt == 1:
                logger.warning(
                    "StartDeploy %s: deadline exceeded, retrying", deploy.id
                )
                continue
            if code in _RETRYABLE_POLL:
                logger.warning(
                    "StartDeploy %s: %s %s", deploy.id, code.name, e.details()
                )
                reason = "builder unavailable, try again"
            else:
                logger.error(
                    "StartDeploy %s: %s %s", deploy.id, code.name, e.details()
                )
                reason = "internal error"
            await _write(ctx, deploy.id, status="failed", error=f"build failed: {reason}")
            return None

    return await _write(ctx, deploy.id, status="building")


async def _await_build(ctx: RunnerContext, deploy: Deploy) -> Deploy | None:
    """building -> starting (or failed): poll GetDeploy until a final state."""
    try:
        result = await _wait_for_build(ctx, deploy.id)
    except grpc.aio.AioRpcError as e:
        if e.code() != grpc.StatusCode.NOT_FOUND:
            raise
        logger.warning("deploy %s: builder does not know the build", deploy.id)
        await _write(ctx, deploy.id, status="failed", error="build lost")
        return None

    if result.state != "SUCCEEDED":
        await _write(
            ctx,
            deploy.id,
            status="failed",
            error=result.error or f"build {result.state.lower()}",
        )
        return None

    return await _write(
        ctx,
        deploy.id,
        status="starting",
        commit_sha=result.commit_sha,
        image=f"{result.image_repository}@{result.image_digest}",
    )


async def _ensure_replica(ctx: RunnerContext, deploy: Deploy) -> ReplicaResult:
    """The deploy's replica: the one already running (a resumed deploy), else RunReplica."""
    replica_id = f"{deploy.id}-r0"
    found = await find_replica(ctx.agents, replica_id)
    if found is not None and found[1].state == "RUNNING":
        node, info = found
        logger.info("deploy %s: replica %s already on %s", deploy.id, replica_id, node)
        return ReplicaResult(replica_id, node, info.host_port)

    app = await ctx.apps.get_app_unchecked(deploy.app_name)
    repository, _, digest = deploy.image.rpartition("@")
    return await ctx.agents.run_replica(
        node=pick_runner(ctx.agents.runner_names),
        replica_id=replica_id,
        app_id=deploy.app_name,
        image_repository=repository,
        image_digest=digest,
        container_port=CONTAINER_PORT,
        env={
            **app.env,
            # Platform variables last: the user cannot override them.
            "PORT": str(CONTAINER_PORT),
            "FORWARDED_ALLOW_IPS": ctx.trusted_proxy,
        },
        cpu_millicores=DEFAULT_CPU_MILLICORES,
        memory_bytes=DEFAULT_MEMORY_BYTES,
    )


async def _publish_and_finish(
    ctx: RunnerContext, deploy: Deploy, replica: ReplicaResult
) -> None:
    """starting -> running: publish the route, then mark the deploy; compensate on failure."""
    this_route = Route(
        deploy.app_name, node_ip(ctx.runner_addrs[replica.node]), replica.host_port
    )
    compensate = False  # the route was not published: undo RunReplica below
    async with ctx.routes.lock:
        async with ctx.uow_factory() as uow:  # released before apply/wait_applied
            current = await uow.deploys.get(deploy.id)
            deploys = await uow.deploys.list_all()
        if current is None:
            # The app was deleted while the replica was starting: don't publish.
            _log_cancelled(deploy.id)
            compensate = True
        elif current.lease_owner != ctx.owner:
            _log_lost(deploy.id)
            return
        else:
            desired = running_routes(
                deploys, ctx.runner_addrs, skip_app=deploy.app_name
            )
            desired.append(this_route)
            try:
                stopped = await stopped_apps(ctx.apps, desired, deploy.app_name)
                gen = ctx.routes.apply(desired, stopped)
                await ctx.routes.wait_applied(gen)
            except (RouteApplyError, TimeoutError) as e:
                logger.warning("deploy %s: route failed: %r", deploy.id, e)
                compensate = await _fail(
                    ctx,
                    deploy.id,
                    "route failed: could not publish the app's address",
                    None,
                )

    if compensate:
        # Outside the lock: a node RPC must not block other deploys.
        await _remove_replica(ctx.agents, replica)
        return

    if await _write(
        ctx,
        deploy.id,
        status="running",
        node=replica.node,
        host_port=replica.host_port,
    ):
        logger.info(
            "deploy %s running on %s:%d", deploy.id, replica.node, replica.host_port
        )
        await _retire_previous(ctx, deploy)
    elif await _is_deleted(ctx, deploy.id):
        # Deleted during wait_applied: the AppDeleted handler re-applies the routes after us.
        await _remove_replica(ctx.agents, replica)


async def _retire_previous(ctx: RunnerContext, deploy: Deploy) -> None:
    """Pivot of a redeploy: the route points at `deploy`, so older running deploys of the app
    become superseded and their replicas go. Never fails the new deploy; a replica left
    behind is removed by the startup check.
    """
    try:
        async with ctx.uow_factory() as uow:
            older = [
                d
                for d in await uow.deploys.list_running(deploy.app_name)
                if d.id != deploy.id
            ]
            for d in older:
                _ = await uow.deploys.update(d.id, status="superseded")
            await uow.commit()
    except Exception:
        logger.warning(
            "deploy %s: could not supersede the previous deploys", deploy.id, exc_info=True
        )
        return

    for d in older:
        if await remove_replica_quietly(ctx.agents, d.node, f"{d.id}-r0"):
            logger.info("deploy %s: superseded %s, its replica is removed", deploy.id, d.id)


async def _fail(
    ctx: RunnerContext, deploy_id: str, error: str, replica: ReplicaResult | None
) -> bool:
    """Mark failed and remove the replica; True if the replica was ours to remove.

    A lost lease means someone else owns the deploy now: leave its replica alone.
    """
    ours = await _write(ctx, deploy_id, status="failed", error=error) is not None
    ours = ours or await _is_deleted(ctx, deploy_id)
    if ours:
        await _remove_replica(ctx.agents, replica)
    return ours


async def _write(ctx: RunnerContext, deploy_id: str, **changes) -> Deploy | None:
    """One fenced write step in its own UoW; None if the deploy is gone or the lease was lost."""
    if changes.get("status") in _LEASE_ENDS_WITH:
        changes = {**changes, "lease_owner": "", "lease_until": None}
    async with ctx.uow_factory() as uow:
        deploy = await uow.deploys.update_owned(deploy_id, ctx.owner, **changes)
        if deploy is None:
            _log_lost(deploy_id)
            return None
        await uow.commit()
        return deploy


async def _is_deleted(ctx: RunnerContext, deploy_id: str) -> bool:
    """A missing row means the app was deleted."""
    async with ctx.uow_factory() as uow:
        return await uow.deploys.get(deploy_id) is None


def _log_cancelled(deploy_id: str) -> None:
    logger.info("deploy %s: deploy cancelled (app deleted)", deploy_id)


def _log_lost(deploy_id: str) -> None:
    logger.info("deploy %s: lease lost or deploy deleted, stopping", deploy_id)


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


async def list_replicas_by_node(
    agents: Agents,
) -> tuple[dict[str, list[ReplicaInfo]], set[str]]:
    """Replicas of every reachable runner, and the names of the runners that did not answer."""
    names = agents.runner_names
    answers = await asyncio.gather(
        *(agents.list_replicas(n) for n in names), return_exceptions=True
    )
    by_node: dict[str, list[ReplicaInfo]] = {}
    unreachable: set[str] = set()
    for name, answer in zip(names, answers, strict=True):
        if isinstance(answer, BaseException):
            if not isinstance(answer, Exception):
                raise answer  # cancellation
            logger.warning("could not list replicas on %s: %r", name, answer)
            unreachable.add(name)
        else:
            by_node[name] = answer
    return by_node, unreachable


async def find_replica(
    agents: Agents, replica_id: str
) -> tuple[str, ReplicaInfo] | None:
    """(node, replica) if some reachable runner has it."""
    by_node, _ = await list_replicas_by_node(agents)
    for node, replicas in by_node.items():
        for info in replicas:
            if info.replica_id == replica_id:
                return node, info
    return None


async def _wait_for_build(ctx: RunnerContext, deploy_id: str) -> DeployResult:
    """Poll GetDeploy until a final state, retrying short outages."""
    failures = 0
    while True:
        try:
            result = await ctx.agents.get_deploy(deploy_id)
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
            await asyncio.sleep(min(ctx.poll_interval * 2**failures, 15))
            continue
        failures = 0
        if result.state in _FINAL_STATES:
            return result
        await asyncio.sleep(ctx.poll_interval)
