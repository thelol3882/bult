"""Shared fixtures for tests/ and app/<domain>/tests/."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apps.deps import get_app_repo
from app.apps.repositories.apps import InMemoryAppRepository
from app.core.config import Settings
from app.core.deps import get_agents, get_routes, get_settings
from app.deploys.deps import get_deploy_repo
from app.deploys.repositories.deploys import InMemoryDeployRepository
from app.main import create_app
from tests.fakes import DOMAIN, RUNNERS, TRUSTED_PROXY, FakeAgentClients, FakeRoutes


@pytest.fixture
def routes(tmp_path: Path) -> FakeRoutes:
    return FakeRoutes(tmp_path / "routes", DOMAIN)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        builder="builder:50051",
        runners=RUNNERS,
        trusted_proxy=TRUSTED_PROXY,
        ingress_dir=str(tmp_path / "routes"),
    )


@pytest.fixture
def app_repo() -> InMemoryAppRepository:
    return InMemoryAppRepository()


@pytest.fixture
def deploy_repo() -> InMemoryDeployRepository:
    return InMemoryDeployRepository()


@pytest.fixture
def agents() -> FakeAgentClients:
    """Agents that never fail."""
    return FakeAgentClients()


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_repo: InMemoryAppRepository,
    deploy_repo: InMemoryDeployRepository,
    routes: FakeRoutes,
    settings: Settings,
    agents: FakeAgentClients,
) -> Iterator[FastAPI]:
    """A fresh app with fakes wired in; the env vars feed the lifespan when a test runs it."""
    monkeypatch.setenv("BULT_BUILDER", "builder:50051")
    monkeypatch.setenv("BULT_RUNNERS", "node-a=runner:50051")
    monkeypatch.setenv("BULT_TRUSTED_PROXY", TRUSTED_PROXY)
    monkeypatch.setenv("BULT_INGRESS_DIR", str(tmp_path / "lifespan-routes"))

    application = create_app()
    # The single place tests configure collaborators. Event handlers read app.state;
    # the overrides keep the same objects when a test runs the lifespan (it would replace the state).
    application.state.app_repo = app_repo
    application.state.deploy_repo = deploy_repo
    application.state.deploy_tasks = set()
    application.state.agents = agents
    application.state.routes = routes
    application.state.settings = settings
    application.dependency_overrides[get_app_repo] = lambda: app_repo
    application.dependency_overrides[get_deploy_repo] = lambda: deploy_repo
    application.dependency_overrides[get_routes] = lambda: routes
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_agents] = lambda: agents
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """In-process client without a lifespan."""
    return TestClient(app)
