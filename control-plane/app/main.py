"""Application factory: `uvicorn app.main:create_app --factory`."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app import health
from app.agents.client import AgentClients
from app.apps.events import AppDeleted
from app.apps.public import build_apps_facade
from app.apps.repositories.apps import InMemoryAppRepository
from app.apps.routers import apps as apps_router
from app.core import exception_handlers
from app.core.config import Settings
from app.core.events import EventBus
from app.core.logging import setup_logging
from app.core.middleware import TraceIdMiddleware
from app.deploys import handlers as deploys_handlers
from app.deploys.deps import build_deploy_service
from app.deploys.repositories.deploys import InMemoryDeployRepository
from app.deploys.routers import deploys as deploys_router
from app.ingress.routes import RouteWriter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create long-lived resources once the event loop exists; close them on shutdown."""
    settings = Settings()  # pyright: ignore[reportCallIssue]
    app.state.settings = settings
    app.state.agents = AgentClients(settings.builder, settings.runners)
    app.state.routes = RouteWriter(Path(settings.ingress_dir), settings.apps_domain)
    # In-memory until PostgreSQL storage lands.
    app.state.app_repo = InMemoryAppRepository()
    app.state.deploy_repo = InMemoryDeployRepository()
    app.state.deploy_tasks = set()
    yield

    tasks = app.state.deploy_tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await app.state.agents.close()


def _build_event_bus(app: FastAPI) -> EventBus:
    """Wire subscriptions; the service is built from app.state when an event arrives."""
    bus = EventBus()

    async def on_app_deleted(event: AppDeleted) -> None:
        state = app.state
        deploys = build_deploy_service(
            state.deploy_repo,
            build_apps_facade(state.app_repo, state.settings, bus.collector()),
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
    app.include_router(apps_router.router)
    app.include_router(deploys_router.router)

    return app
