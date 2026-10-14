"""Application factory: `uvicorn app.main:create_app --factory`."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app import health
from app.agents.client import AgentClients
from app.apps.events import AppDeleted
from app.apps.public import build_apps_facade
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
from app.deploys.uow import sql_deploys_uow_factory
from app.ingress.routes import RouteWriter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create long-lived resources once the event loop exists; close them on shutdown."""
    settings = Settings()  # pyright: ignore[reportCallIssue]
    app.state.settings = settings

    app.state.agents = AgentClients(settings.builder, settings.runners)
    app.state.routes = RouteWriter(Path(settings.ingress_dir), settings.apps_domain)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    app.state.db_engine = engine

    app.state.apps_uow_factory = sql_apps_uow_factory(session_factory)

    app.state.deploys_uow_factory = sql_deploys_uow_factory(session_factory)
    app.state.deploy_tasks = set()

    app.state.auth_uow_factory = sql_auth_uow_factory(session_factory)
    app.state.password_hasher = PasswordHasher()
    app.state.token_issuer = TokenIssuer(
        secret=settings.jwt_secret.get_secret_value(),
        ttl_seconds=settings.jwt_ttl_seconds,
    )

    yield

    tasks = app.state.deploy_tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await app.state.agents.close()
    await app.state.db_engine.dispose()


def _build_event_bus(app: FastAPI) -> EventBus:
    """Wire subscriptions; the service is built from app.state when an event arrives."""
    bus = EventBus()

    async def on_app_deleted(event: AppDeleted) -> None:
        state = app.state

        deploys = build_deploy_service(
            state.deploys_uow_factory,
            build_apps_facade(
                uow_factory=state.apps_uow_factory,
                settings=state.settings,
                events=bus.collector(),
            ),
            state.agents,
            state.routes,
            state.settings,
            state.deploy_tasks,
        )
        await deploys_handlers.on_app_deleted(event, deploys)

    bus.subscribe(AppDeleted, on_app_deleted)
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

    app.add_middleware(TraceIdMiddleware)
    exception_handlers.register(app)

    app.include_router(health.router)
    app.include_router(auth_router.router)
    app.include_router(apps_router.router)
    app.include_router(deploys_router.router)

    return app
