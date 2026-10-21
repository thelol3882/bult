"""Application factory: `uvicorn app.main:create_app --factory`."""

import asyncio
import dataclasses
import logging
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app import health
from app.agents.client import AgentClients
from app.apps.events import AppDeleted, AppRoutesChanged
from app.apps.public import AppsFacade, build_apps_facade
from app.apps.routers import apps as apps_router
from app.apps.uow import sql_apps_uow_factory
from app.auth.routers import auth as auth_router
from app.auth.services.passwords import PasswordHasher
from app.auth.services.tokens import TokenIssuer
from app.auth.uow import sql_auth_uow_factory
from app.core import exception_handlers
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.events import EventBus
from app.core.logging import setup_logging
from app.core.middleware import TraceIdMiddleware
from app.deploys import handlers as deploys_handlers
from app.deploys.deps import build_deploy_service
from app.deploys.routers import deploys as deploys_router
from app.deploys.routers import lifecycle as lifecycle_router
from app.deploys.services.deploys import DeployService
from app.deploys.services.facade import DeploysFacade
from app.deploys.services.health import HealthState, Observation, ReplicaHealthService
from app.deploys.services.reconciler import Reconciler
from app.deploys.services.reconcile import (
    fail_deploys_without_replica,
    remove_orphan_replicas,
)
from app.deploys.services.worker import DeployWorker
from app.deploys.uow import sql_deploys_uow_factory
from app.ingress.routes import RouteWriter
from app.metrics import handlers as metrics_handlers
from app.metrics.routers import metrics as metrics_router
from app.metrics.services.metrics import MetricsService, UsageSample
from app.metrics.services.retention import RetentionLoop
from app.metrics.uow import sql_metrics_uow_factory
from app.nodes.routers import internal as nodes_internal_router
from app.nodes.routers import nodes as nodes_router
from app.nodes.services.facade import NodesFacade
from app.nodes.services.monitor import NodeMonitor
from app.nodes.services.nodes import NodeService, ReplicaHealth, ReplicaUsage
from app.nodes.uow import sql_nodes_uow_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create long-lived resources once the event loop exists; close them on shutdown."""
    settings = Settings()  # pyright: ignore[reportCallIssue]
    app.state.settings = settings

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    app.state.db_engine = engine

    app.state.nodes_uow_factory = sql_nodes_uow_factory(session_factory)
    app.state.node_service = NodeService(app.state.nodes_uow_factory, settings)
    app.state.nodes = NodesFacade(app.state.node_service)

    app.state.agents = AgentClients(app.state.nodes)
    app.state.routes = RouteWriter(
        Path(settings.ingress_dir), settings.apps_domain, settings.lb_algorithm
    )

    app.state.apps_uow_factory = sql_apps_uow_factory(session_factory)

    app.state.deploys_uow_factory = sql_deploys_uow_factory(session_factory)

    app.state.auth_uow_factory = sql_auth_uow_factory(session_factory)
    app.state.metrics_uow_factory = sql_metrics_uow_factory(session_factory)
    app.state.password_hasher = PasswordHasher()
    app.state.token_issuer = TokenIssuer(
        secret=settings.jwt_secret.get_secret_value(),
        ttl_seconds=settings.jwt_ttl_seconds,
    )

    apps_facade = build_apps_facade(
        uow_factory=app.state.apps_uow_factory,
        settings=settings,
        events=app.state.event_bus.collector(),
    )
    app.state.deploys = DeploysFacade(app.state.deploys_uow_factory, app.state.nodes)
    app.state.metrics = MetricsService(
        app.state.metrics_uow_factory,
        apps_facade,
        app.state.deploys,
        retention_hours=settings.metrics_retention_hours,
    )
    retention = RetentionLoop(
        app.state.metrics.purge, settings.metrics_retention_interval
    )
    worker = DeployWorker(
        app.state.agents,
        app.state.deploys_uow_factory,
        apps_facade,
        app.state.nodes,
        app.state.routes,
        settings.trusted_proxy,
    )
    monitor = NodeMonitor(
        app.state.node_service,
        on_change=lambda: _reapply_routes_quietly(app, apps_facade),
        interval=settings.node_monitor_interval,
        initial_delay=settings.node_ttl_seconds,
    )
    reconciler = Reconciler(
        app.state.health_state,
        app.state.deploys_uow_factory,
        app.state.agents,
        app.state.nodes,
        apps_facade,
        lambda what: _reapply_routes(app, apps_facade, what),
        settings.trusted_proxy,
        interval=settings.reconcile_interval,
        initial_delay=settings.node_ttl_seconds,
    )
    startup_check: asyncio.Task[None] | None = None
    if settings.reconciler:
        reconciler.start()
    if settings.deploy_worker:
        worker.start()
        startup_check = asyncio.create_task(_startup_check(app))
    if settings.node_monitor:
        monitor.start()
    if settings.metrics_retention:
        retention.start()

    yield

    await retention.stop()
    await reconciler.stop()
    await monitor.stop()
    if startup_check is not None:
        startup_check.cancel()
        await asyncio.gather(startup_check, return_exceptions=True)
    await worker.stop()
    await app.state.agents.close()
    await app.state.db_engine.dispose()


async def _reapply_routes(
    app: FastAPI, apps: AppsFacade, what: str = "node status change"
) -> int | None:
    """Render the routes again from the database and the nodes' health."""
    state = app.state
    service = build_deploy_service(
        state.deploys_uow_factory,
        apps,
        state.agents,
        state.nodes,
        state.routes,
        state.settings,
    )
    return await service.reapply_routes(what)


async def _reapply_routes_quietly(app: FastAPI, apps: AppsFacade) -> None:
    """A node became unhealthy or came back: the routes follow."""
    _ = await _reapply_routes(app, apps)


async def _record_health(
    app: FastAPI, node: str, health: Sequence[ReplicaHealth], complete: bool
) -> None:
    """Hand a node's replica states to the deploys domain and wake the reconciler if needed."""
    if not health and not complete:
        return
    state = app.state
    service = ReplicaHealthService(state.deploys_uow_factory, state.health_state)
    result = await service.record(
        node, [Observation(**dataclasses.asdict(h)) for h in health], complete
    )
    if result.routes_changed:
        state.health_state.signal.routes_changed()
    for replica_id in result.garbage:
        state.health_state.signal.collect(node, replica_id)


async def _replica_counts(app: FastAPI) -> dict[str, int]:
    async with app.state.deploys_uow_factory() as uow:
        return await uow.replicas.count_running_by_node()


async def _store_usage(app: FastAPI, node: str, usage: Sequence[ReplicaUsage]) -> None:
    """Hand a node's replica readings to the metrics domain."""
    samples = [UsageSample(**dataclasses.asdict(u)) for u in usage]
    _ = await app.state.metrics.record(node, samples)


async def _startup_check(app: FastAPI) -> None:
    """Reconcile the database with the nodes after a start.

    Deploys marked running whose replica vanished (wiped node, restarted VM) become failed;
    replicas whose deploy is not running (leftovers of a redeploy or stop) are removed.
    """
    state = app.state
    apps = build_apps_facade(
        uow_factory=state.apps_uow_factory,
        settings=state.settings,
        events=state.event_bus.collector(),
    )
    try:
        failed = await fail_deploys_without_replica(
            state.agents,
            state.deploys_uow_factory,
            state.routes,
            state.nodes,
            apps,
        )
        removed = await remove_orphan_replicas(state.agents, state.deploys_uow_factory)
    except Exception:
        logger.exception("startup check failed")
        return
    if failed:
        logger.warning("startup check: %d deploy(s) lost their replica", len(failed))
    if removed:
        logger.warning("startup check: removed %d orphan replica(s)", len(removed))


def _build_event_bus(app: FastAPI) -> EventBus:
    """Wire subscriptions; the service is built from app.state when an event arrives."""
    bus = EventBus()

    def deploys_service() -> DeployService:
        state = app.state
        return build_deploy_service(
            state.deploys_uow_factory,
            build_apps_facade(
                uow_factory=state.apps_uow_factory,
                settings=state.settings,
                events=bus.collector(),
            ),
            state.agents,
            state.nodes,
            state.routes,
            state.settings,
        )

    async def on_app_deleted(event: AppDeleted) -> None:
        await deploys_handlers.on_app_deleted(event, deploys_service())

    async def on_app_routes_changed(event: AppRoutesChanged) -> None:
        await deploys_handlers.on_app_routes_changed(event, deploys_service())

    async def forget_app_metrics(event: AppDeleted) -> None:
        await metrics_handlers.on_app_deleted(event, app.state.metrics)

    bus.subscribe(AppDeleted, on_app_deleted)
    bus.subscribe(AppDeleted, forget_app_metrics)
    bus.subscribe(AppRoutesChanged, on_app_routes_changed)
    return bus


def create_app() -> FastAPI:
    """Build the app with routers, error handling and middleware."""
    setup_logging()
    app = FastAPI(
        title="Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.event_bus = _build_event_bus(app)
    app.state.replica_counts = lambda: _replica_counts(app)
    app.state.usage_sink = lambda node, usage: _store_usage(app, node, usage)
    app.state.health_state = HealthState()
    app.state.health_sink = lambda node, health, complete: _record_health(
        app, node, health, complete
    )

    app.add_middleware(TraceIdMiddleware)
    exception_handlers.register(app)

    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(nodes_router.router)
    app.include_router(nodes_internal_router.router)
    app.include_router(apps_router.router)
    app.include_router(deploys_router.router)
    app.include_router(lifecycle_router.router)
    app.include_router(metrics_router.router)

    return app
