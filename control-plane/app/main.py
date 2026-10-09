"""Control plane application factory.

uvicorn runs it as `app.main:create_app --factory` (see compose.yaml):
every call builds a fresh app — tests get their own app and their own state.
"""

from fastapi import FastAPI

from app.api import apps, health
from app.services.apps import AppStore


def create_app() -> FastAPI:
    """Build the FastAPI application with all routers and shared state."""
    app = FastAPI(
        title="Control Plane",
        version="0.1.0",
    )

    app.state.app_store = AppStore()

    app.include_router(health.router)
    app.include_router(apps.router)

    return app
