"""Shared fixtures: pytest picks this file up for every test in tests/."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_app_store, get_routes, get_settings
from app.core.config import Settings
from app.main import create_app
from app.services.apps import AppStore
from app.services.nginx import Route, RouteWriter

RUNNERS = {"node-a": "10.0.0.5:50051"}


class FakeRoutes(RouteWriter):
    """A real RouteWriter on a temp dir whose "sidecar" accepts every version at once."""

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir)
        self.applied: list[list[Route]] = []

    def apply(self, routes: list[Route]) -> int:
        self.applied.append(list(routes))
        return super().apply(routes)

    async def wait_applied(self, generation: int, timeout: float = 10.0) -> None:
        return None


@pytest.fixture
def routes(tmp_path: Path) -> FakeRoutes:
    return FakeRoutes(tmp_path / "routes")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        builder_addr="builder:50051",
        runner_addrs=RUNNERS,
        trusted_proxy="10.0.0.1",
        ingress_dir=str(tmp_path / "routes"),
    )


@pytest.fixture
def store() -> AppStore:
    """A fresh in-memory store for every test."""
    return AppStore()


@pytest.fixture
def app(store: AppStore, routes: FakeRoutes, settings: Settings):
    """A fresh FastAPI application with the store, routes and settings overridden
    (no lifespan here: nothing would create them otherwise)."""
    application = create_app()
    application.dependency_overrides[get_app_store] = lambda: store
    application.dependency_overrides[get_routes] = lambda: routes
    application.dependency_overrides[get_settings] = lambda: settings
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Synchronous test client: calls the app in-process, no server needed."""
    return TestClient(app)
