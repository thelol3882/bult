"""Deploys domain rules and errors. Calls the apps domain through its facade, never its repository."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import grpc

from app.agents.client import Agents, ReplicaResult, UnknownNodeError
from app.apps.services.facade import App, AppsFacade
from app.core.config import MAX_REPLICAS, Settings
from app.core.error_codes import ErrorCode
from app.core.errors import (
    ConflictError,
    InternalError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.principal import Principal
from app.deploys.errors import DeployInProgressError
from app.deploys.repositories.deploys import ACTIVE_STATUSES, Deploy
from app.deploys.repositories.replicas import Replica, ReplicaView
from app.deploys.services.health import to_view
from app.deploys.services.routing import current_routes, routing_state
from app.deploys.services.runner import place_replicas, remove_replica_quietly
from app.deploys.services.scheduler import pick_victims
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteApplyError, RouteWriter
from app.nodes.services.facade import NodesFacade

logger = logging.getLogger(__name__)


class DeployNotFoundError(NotFoundError):
    """No deploy with this id for this app."""

    code = ErrorCode.DEPLOY_NOT_FOUND

    def __init__(self, deploy_id: str) -> None:
        super().__init__(f"Deploy '{deploy_id}' not found.")


class NothingToStartError(ConflictError):
    """The app never ran, so there is no image to start."""

    code = ErrorCode.NOTHING_TO_START

    def __init__(self, name: str) -> None:
        super().__init__(f"App '{name}' has nothing to start: deploy the app first.")


class AppAlreadyRunningError(ConflictError):
    """Start of an app that is up."""

    code = ErrorCode.APP_ALREADY_RUNNING

    def __init__(self, name: str) -> None:
        super().__init__(f"App '{name}' is already running.")


class DeployNotRestorableError(ConflictError):
    """The deploy never ran or has no image to reuse."""

    code = ErrorCode.DEPLOY_NOT_RESTORABLE

    def __init__(self, deploy_id: str) -> None:
        super().__init__(
            f"Deploy '{deploy_id}' never ran or has no image, so it cannot be restored."
        )


class DeployNotCancellableError(ConflictError):
    """The deploy is past the point where a cancel can stop it."""

    code = ErrorCode.DEPLOY_NOT_CANCELLABLE


class ReplicaNotFoundError(NotFoundError):
    """The running deploy has no replica with this index."""

    code = ErrorCode.REPLICA_NOT_FOUND

    def __init__(self, index: int) -> None:
        super().__init__(f"The app has no running replica {index}.")


class NoNodeAvailableError(ServiceUnavailableError):
    """No ready node accepted a new replica."""

    code = ErrorCode.NO_NODE_AVAILABLE

    def __init__(self) -> None:
        super().__init__("No node could start the replica. Try again later.")


class NodeUnavailableError(ServiceUnavailableError):
    """The node with the replica did not answer."""

    code = ErrorCode.NODE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("The node running the app is not reachable. Try again later.")


class BuilderUnavailableError(ServiceUnavailableError):
    """The builder did not answer."""

    code = ErrorCode.BUILDER_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("The build node is not reachable. Try again later.")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AppLogs:
    """The tail of the output of one replica of the app's running deploy."""

    deploy_id: str | None  # None: nothing is running
    replica: int | None  # index of the replica the lines come from
    lines: list[str]


@dataclass(frozen=True)
class Scaled:
    """Result of a scale request."""

    replicas: int
    deploy: Deploy | None  # the running deploy, or the deploy that starts the app; None if stopped


class DeployService:
    def __init__(
        self,
        uow_factory: Callable[[], DeploysUoW],
        apps: AppsFacade,
        agents: Agents,
        nodes: NodesFacade,
        routes: RouteWriter,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._apps = apps
        self._agents = agents
        self._nodes = nodes
        self._routes = routes
        self._settings = settings

    async def start(self, app_name: str, principal: Principal) -> Deploy:
        """Queue a deploy; the worker does the rest. DeployInProgressError if one is active."""
        app = await self._apps.get_app(app_name, principal)
        desired = max(app.replicas, 1)
        deploy = await self._queue(
            Deploy(id=uuid.uuid4().hex, app_name=app.name, desired_replicas=desired)
        )
        await self._wake(app, desired, principal)
        return await self._view(deploy)

    async def stop_app(self, app_name: str, principal: Principal) -> None:
        """replicas -> 0: deploys `stopped`, routes re-applied (stopped page), replicas removed."""
        await self._apps.get_app(app_name, principal)
        await self._reject_if_deploy_active(app_name)
        await self._stop(app_name, principal)

    async def start_app(self, app_name: str, principal: Principal) -> Deploy:
        """Run the app again from the image of the last deploy that ran: no build."""
        app = await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            if app.replicas > 0 and await uow.deploys.list_running(app_name):
                raise AppAlreadyRunningError(app_name)
            source = await uow.deploys.latest_restorable(app_name)
        if source is None:
            raise NothingToStartError(app_name)
        return await self._view(
            await self._queue_from_image(app, source, max(app.replicas, 1), principal)
        )

    async def rollback(
        self, app_name: str, deploy_id: str, principal: Principal
    ) -> Deploy:
        """Run the image of an earlier deploy as a new deploy: no build."""
        app = await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            source = await uow.deploys.get(deploy_id)
        if source is None or source.app_name != app_name:
            raise DeployNotFoundError(deploy_id)
        if not source.restorable:
            raise DeployNotRestorableError(deploy_id)
        return await self._view(
            await self._queue_from_image(app, source, max(app.replicas, 1), principal)
        )

    async def scale_app(
        self, app_name: str, replicas: int, principal: Principal
    ) -> Scaled:
        """Change the number of replicas of the running deploy: same image, no build.

        0 stops the app. More adds replicas (placed by the scheduler), fewer removes the
        highest-numbered ones; the routes follow. An app that is not running starts again
        from its last image.
        """
        app = await self._apps.get_app(app_name, principal)
        await self._reject_if_deploy_active(app_name)

        if replicas == 0:
            await self._stop(app_name, principal)
            return Scaled(0, None)

        async with self._uow_factory() as uow:
            running = await uow.deploys.list_running(app_name)
            source = None if running else await uow.deploys.latest_restorable(app_name)
            rows = (
                await uow.replicas.list_running([running[0].id]) if running else []
            )
        if not running:
            if source is None:
                raise NothingToStartError(app_name)
            _ = await self._apps.set_replicas(app_name, replicas, principal)
            deploy = await self._queue_from_image(app, source, replicas, principal)
            return Scaled(replicas, await self._view(deploy))

        deploy = running[0]
        async with self._uow_factory() as uow:  # a scale gives crash-looping replicas another chance
            if await uow.replicas.reset_crashloops(deploy.id):
                await uow.commit()
                rows = await uow.replicas.list_running([deploy.id])
        retired: list[Replica] = []
        if replicas > len(rows):
            await self._add_replicas(deploy, app, rows, replicas)
        elif replicas < len(rows):
            ready = {n.name for n in await self._nodes.runners() if n.ready}
            retired = await self._retire_replicas(rows, replicas, ready)

        _ = await self._apps.set_replicas(app_name, replicas, principal)
        async with self._uow_factory() as uow:
            _ = await uow.deploys.update(deploy.id, desired_replicas=replicas)
            await uow.commit()
        # Routes first: stop sending traffic to the retired replicas, then remove them.
        _ = await self._reapply_routes(f"scale {app_name}")
        for r in retired:
            _ = await remove_replica_quietly(self._agents, r.node, r.id)
        # Fresh read: the rows changed.
        async with self._uow_factory() as uow:
            current = await uow.deploys.get(deploy.id)
        return Scaled(replicas, await self._view(current) if current else None)

    async def _add_replicas(
        self, deploy: Deploy, app: App, rows: list[Replica], target: int
    ) -> None:
        used = {r.index for r in rows}
        free = [i for i in range(MAX_REPLICAS) if i not in used]
        wanted = free[: target - len(rows)]
        placed: list[ReplicaResult] = []
        error = await place_replicas(
            self._agents,
            self._nodes,
            self._uow_factory,
            deploy,
            app,
            wanted,
            placed,
            self._settings.trusted_proxy,
        )
        if not placed:
            logger.warning("scale %s: no replica started: %r", app.name, error)
            raise NoNodeAvailableError()
        if error is not None:
            logger.warning(
                "scale %s: %d of %d new replicas started: %r",
                app.name,
                len(placed),
                len(wanted),
                error,
            )

    async def _retire_replicas(
        self, rows: list[Replica], target: int, ready: set[str]
    ) -> list[Replica]:
        """Mark the replicas to drop removed (see pick_victims); the caller removes the containers."""
        victims = pick_victims(rows, len(rows) - target, ready)
        async with self._uow_factory() as uow:
            await uow.replicas.mark_removed(r.id for r in victims)
            await uow.commit()
        return victims

    async def cancel(
        self, app_name: str, deploy_id: str, principal: Principal
    ) -> Deploy:
        """Cancel a queued or building deploy.

        queued: written directly, no agent call. building: the builder is asked to stop and
        the worker writes the final `cancelled` when it sees the CANCELLED build.
        """
        deploy = await self.get(app_name, deploy_id, principal)
        if deploy.status == "queued":
            async with self._uow_factory() as uow:
                cancelled = await uow.deploys.cancel_queued(deploy_id, _utcnow())
                await uow.commit()
            if cancelled is not None:
                return await self._view(cancelled)
            # The worker took it between the read and the write: look again.
            deploy = await self.get(app_name, deploy_id, principal)

        if deploy.status == "starting":
            raise DeployNotCancellableError(
                "The deploy is already starting the app and can no longer be cancelled."
            )
        if deploy.status not in ("queued", "building"):
            raise DeployNotCancellableError(
                f"The deploy has already finished ({deploy.status})."
            )

        try:
            result = await self._agents.cancel_deploy(deploy_id)
        except grpc.aio.AioRpcError as e:
            code = e.code()
            logger.warning("cancel %s: %s %s", deploy_id, code.name, e.details())
            if code == grpc.StatusCode.NOT_FOUND and deploy.status == "queued":
                # Claimed, but the builder has not heard of it yet.
                raise DeployNotCancellableError(
                    "The deploy is just being picked up. Try again in a moment."
                ) from None
            if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                raise BuilderUnavailableError() from None
            if code == grpc.StatusCode.NOT_FOUND:
                return deploy  # the builder lost the build: the worker fails the deploy
            raise InternalError("Could not cancel the deploy.") from None

        if result.state in ("SUCCEEDED", "FAILED"):
            raise DeployNotCancellableError("The build has already finished.")
        return deploy

    async def logs(
        self,
        app_name: str,
        tail: int,
        principal: Principal,
        replica: int | None = None,
    ) -> AppLogs:
        """Last `tail` lines of one replica of the running deploy: the given index, else the
        lowest-numbered one on a ready node."""
        await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            running = await uow.deploys.list_running(app_name)
            rows = (
                await uow.replicas.list_running([running[0].id]) if running else []
            )
        if not running:
            if replica is not None:
                raise ReplicaNotFoundError(replica)
            return AppLogs(deploy_id=None, replica=None, lines=[])

        deploy = running[0]
        if replica is not None:
            chosen = next((r for r in rows if r.index == replica), None)
            if chosen is None:
                raise ReplicaNotFoundError(replica)
        else:
            ready = {n.name for n in await self._nodes.runners() if n.ready}
            chosen = next((r for r in rows if r.node in ready), rows[0] if rows else None)
            if chosen is None:
                return AppLogs(deploy.id, None, [])

        try:
            text = await self._agents.logs(
                node=chosen.node, replica_id=chosen.id, tail_lines=tail
            )
        except grpc.aio.AioRpcError as e:
            code = e.code()
            if code == grpc.StatusCode.NOT_FOUND:  # the replica vanished: nothing to show
                return AppLogs(deploy.id, chosen.index, [])
            logger.warning("logs %s: %s %s", app_name, code.name, e.details())
            if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                raise NodeUnavailableError() from None
            raise InternalError("Could not read the logs.") from None
        except UnknownNodeError:
            logger.warning("logs %s: unknown node %s", app_name, chosen.node)
            raise InternalError("Could not read the logs.") from None
        return AppLogs(deploy.id, chosen.index, text.splitlines()[-tail:])

    async def _queue(self, deploy: Deploy) -> Deploy:
        async with self._uow_factory() as uow:
            deploy = await uow.deploys.add(deploy)
            await uow.commit()
        return deploy

    async def _queue_from_image(
        self, app: App, source: Deploy, desired: int, principal: Principal
    ) -> Deploy:
        """A deploy that starts at `starting` with the source's image (StartDeploy is skipped)."""
        deploy = await self._queue(
            Deploy(
                id=uuid.uuid4().hex,
                app_name=app.name,
                status="starting",
                commit_sha=source.commit_sha,
                image=source.image,
                desired_replicas=desired,
                source_deploy_id=source.id,
            )
        )
        await self._wake(app, desired, principal)
        return deploy

    async def _wake(self, app: App, desired: int, principal: Principal) -> None:
        """A new deploy of a stopped app makes it wanted again."""
        if app.replicas == 0:
            _ = await self._apps.set_replicas(app.name, desired, principal)

    async def _stop(self, app_name: str, principal: Principal) -> None:
        _ = await self._apps.set_replicas(app_name, 0, principal)

        async with self._uow_factory() as uow:
            running = await uow.deploys.list_running(app_name)
            for deploy in running:
                _ = await uow.deploys.update(deploy.id, status="stopped")
            rows = await uow.replicas.list_running(d.id for d in running)
            await uow.replicas.mark_removed(r.id for r in rows)
            await uow.commit()

        # Routes first: stop sending traffic, then remove the replicas.
        _ = await self._reapply_routes(f"stop {app_name}")
        for r in rows:
            _ = await remove_replica_quietly(self._agents, r.node, r.id)

    async def _reject_if_deploy_active(self, app_name: str) -> None:
        async with self._uow_factory() as uow:
            # An active deploy is always the newest: a second one is refused while it lives.
            newest = await uow.deploys.list_for_app(app_name, None, 1)
        if newest and newest[0].status in ACTIVE_STATUSES:
            raise DeployInProgressError(app_name)

    async def reapply_routes(self, what: str) -> int | None:
        """Render the routes from the database and the nodes' health, wait for the sidecar;
        None if that failed."""
        return await self._reapply_routes(what)

    async def _reapply_routes(self, what: str) -> int | None:
        async with self._routes.lock:
            async with self._uow_factory() as uow:
                desired = await current_routes(uow, self._nodes)
            try:
                desired, stopped = await routing_state(self._apps, desired)
                gen = self._routes.apply(desired, stopped)
                await self._routes.wait_applied(gen)
            except (RouteApplyError, TimeoutError) as e:
                logger.warning("%s: route update failed: %r", what, e)
                return None
        return gen

    async def _view(self, deploy: Deploy) -> Deploy:
        return (await self._views([deploy]))[0]

    async def _views(self, deploys: list[Deploy]) -> list[Deploy]:
        """The deploys with their running replicas and how many of them are on ready nodes."""
        if not deploys:
            return []
        async with self._uow_factory() as uow:
            rows = await uow.replicas.list_running(d.id for d in deploys)
        ready = {n.name: n.ready for n in await self._nodes.runners()}
        now = _utcnow()
        by_deploy: dict[str, list[ReplicaView]] = {}
        serving: dict[str, int] = {}
        for r in rows:
            node_ready = ready.get(r.node, False)
            by_deploy.setdefault(r.deploy_id, []).append(to_view(r, node_ready, now))
            serving[r.deploy_id] = serving.get(r.deploy_id, 0) + (
                r.serving and node_ready
            )
        views = []
        for d in deploys:
            replicas = tuple(by_deploy.get(d.id, []))
            views.append(
                replace(
                    d,
                    replicas=replicas,
                    ready_replicas=serving.get(d.id, 0),
                )
            )
        return views

    async def get(self, app_name: str, deploy_id: str, principal: Principal) -> Deploy:
        """DeployNotFoundError if missing OR if it belongs to another app."""
        await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            deploy = await uow.deploys.get(deploy_id)
            if deploy is None or deploy.app_name != app_name:
                raise DeployNotFoundError(deploy_id)
        return await self._view(deploy)

    async def history(
        self,
        app_name: str,
        before: tuple[datetime, str] | None,
        limit: int,
        principal: Principal,
    ) -> list[Deploy]:
        await self._apps.get_app(app_name, principal)
        async with self._uow_factory() as uow:
            deploys = await uow.deploys.list_for_app(app_name, before, limit)
        return await self._views(deploys)

    async def remove_app(self, app_name: str) -> None:
        """Drop the app's routes and remove its replicas (failures are logged).

        Replicas are found by asking the nodes, not from deploy rows: the FK
        cascade has already deleted the rows when the app row was deleted.
        """
        async with self._uow_factory() as uow:
            await uow.deploys.delete_for_app(app_name)  # no-op after the cascade
            await uow.commit()

        # Routes first: stop sending traffic, then remove the replicas.
        # Always re-applied: a deploy in flight may have published this app's route already.
        gen = await self._reapply_routes(f"delete {app_name}")

        found = 0
        removed = 0
        for node in await self._agents.runner_names():
            try:
                replicas = await self._agents.list_replicas(node)
            except Exception:
                logger.warning(
                    "delete %s: could not list replicas on %s",
                    app_name,
                    node,
                    exc_info=True,
                )
                continue
            for replica in replicas:
                if replica.app_id != app_name:
                    continue
                found += 1
                if await remove_replica_quietly(self._agents, node, replica.replica_id):
                    removed += 1

        logger.info(
            "app %s deleted: %d replicas found, %d removed, route generation %s",
            app_name,
            found,
            removed,
            gen if gen is not None else "-",
        )
