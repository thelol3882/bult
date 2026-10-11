"""Control plane application factory.

uvicorn runs it as `app.main:create_app --factory` (see compose.yaml):
every call builds a fresh app — tests get their own app and their own state.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import apps, deploys, health
from app.core.config import load_settings
from app.core.logging import setup_logging
from app.services.agent_client import AgentClients
from app.services.apps import AppStore
from app.services.deploys import DeployStore
from app.services.nginx import RouteWriter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Long-lived resources: created when the event loop exists, closed on shutdown."""
    settings = load_settings()
    app.state.settings = settings
    app.state.agents = AgentClients(settings.builder_addr, settings.runner_addrs)
    app.state.deploy_tasks = set()
    app.state.routes = RouteWriter(Path(settings.ingress_dir))
    yield

    tasks = app.state.deploy_tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await app.state.agents.close()


def create_app() -> FastAPI:
    """Build the FastAPI application with all routers and shared state."""
    setup_logging()
    app = FastAPI(
        title="Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.app_store = AppStore()
    app.state.deploy_store = DeployStore()

    app.include_router(health.router)
    app.include_router(apps.router)
    app.include_router(deploys.router)

    return app
