"""Shared fixtures for tests/ and app/<domain>/tests/."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.apps.deps import get_apps_uow_factory
from app.apps.uow import InMemoryAppsUoW
from app.auth.deps import get_auth_uow_factory
from app.auth.services.tokens import TokenIssuer
from app.auth.uow import InMemoryAuthUoW
from app.core.config import Settings
from app.core.deps import get_agents, get_routes, get_settings
from app.deploys.deps import get_deploys_uow_factory
from app.deploys.uow import InMemoryDeploysUoW
from app.main import create_app
from app.nodes.deps import get_node_service
from app.nodes.public import get_nodes_facade
from app.nodes.services.nodes import NodeService
from app.nodes.uow import InMemoryNodesUoW
from tests.fakes import (
    DOMAIN,
    NODE_TOKENS,
    RUNNERS,
    TEST_JWT_SECRET,
    TRUSTED_PROXY,
    CheapPasswordHasher,
    FakeAgentClients,
    FakeClock,
    FakeNodes,
    FakeRoutes,
    auth_headers,
)

TEST_DATABASE_URL = "postgresql+asyncpg://test/test"


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
        database_url=TEST_DATABASE_URL,
        jwt_secret=SecretStr(TEST_JWT_SECRET),
        jwt_ttl_seconds=86400,
        node_tokens={name: SecretStr(t) for name, t in NODE_TOKENS.items()},
    )


@pytest.fixture
def apps_uow() -> InMemoryAppsUoW:
    """One fake per test: every 'transaction' sees what the previous one wrote."""
    return InMemoryAppsUoW()


@pytest.fixture
def deploys_uow() -> InMemoryDeploysUoW:
    return InMemoryDeploysUoW()


@pytest.fixture
def auth_uow() -> InMemoryAuthUoW:
    return InMemoryAuthUoW()


@pytest.fixture
def nodes() -> FakeNodes:
    """The runners the deploys domain sees: node-a, ready."""
    return FakeNodes()


@pytest.fixture
def agents(nodes: FakeNodes) -> FakeAgentClients:
    """Agents that never fail."""
    return FakeAgentClients(nodes=nodes)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def nodes_uow() -> InMemoryNodesUoW:
    return InMemoryNodesUoW()


@pytest.fixture
def node_service(
    nodes_uow: InMemoryNodesUoW, settings: Settings, clock: FakeClock
) -> NodeService:
    """The real nodes service on an in-memory repository (heartbeat and /nodes tests)."""
    return NodeService(lambda: nodes_uow, settings, clock=clock, cache_ttl=0)


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    apps_uow: InMemoryAppsUoW,
    deploys_uow: InMemoryDeploysUoW,
    auth_uow: InMemoryAuthUoW,
    routes: FakeRoutes,
    settings: Settings,
    agents: FakeAgentClients,
    nodes: FakeNodes,
    node_service: NodeService,
) -> Iterator[FastAPI]:
    """A fresh app with fakes wired in; the env vars feed the lifespan when a test runs it."""
    monkeypatch.setenv("BULT_BUILDER", "builder:50051")
    monkeypatch.setenv("BULT_RUNNERS", "node-a=runner:50051")
    monkeypatch.setenv("BULT_TRUSTED_PROXY", TRUSTED_PROXY)
    monkeypatch.setenv("BULT_INGRESS_DIR", str(tmp_path / "lifespan-routes"))
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("BULT_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("BULT_DEPLOY_WORKER", "false")
    monkeypatch.setenv("BULT_NODE_MONITOR", "false")

    def apps_uow_factory() -> InMemoryAppsUoW:
        return apps_uow

    def deploys_uow_factory() -> InMemoryDeploysUoW:
        return deploys_uow

    def auth_uow_factory() -> InMemoryAuthUoW:
        return auth_uow

    application = create_app()
    application.state.auth_uow_factory = auth_uow_factory
    application.state.password_hasher = CheapPasswordHasher()
    application.state.token_issuer = TokenIssuer(
        TEST_JWT_SECRET, settings.jwt_ttl_seconds
    )
    application.state.apps_uow_factory = apps_uow_factory
    application.state.deploys_uow_factory = deploys_uow_factory
    application.state.agents = agents
    application.state.nodes = nodes
    application.state.node_service = node_service
    application.state.routes = routes
    application.state.settings = settings
    application.dependency_overrides[get_apps_uow_factory] = lambda: apps_uow_factory
    application.dependency_overrides[get_deploys_uow_factory] = lambda: (
        deploys_uow_factory
    )
    application.dependency_overrides[get_auth_uow_factory] = lambda: auth_uow_factory
    application.dependency_overrides[get_routes] = lambda: routes
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_agents] = lambda: agents
    application.dependency_overrides[get_nodes_facade] = lambda: nodes
    application.dependency_overrides[get_node_service] = lambda: node_service
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def anon_client(app: FastAPI) -> TestClient:
    """In-process client without a lifespan and without credentials."""
    return TestClient(app)


@pytest.fixture
def make_client(app: FastAPI) -> Callable[[str], TestClient]:
    """make_client(email) -> client logged in as that user (registered on first use)."""

    def _make(email: str) -> TestClient:
        return TestClient(app, headers=auth_headers(TestClient(app), email))

    return _make


@pytest.fixture
def client(make_client: Callable[[str], TestClient]) -> TestClient:
    """Client logged in as alice."""
    return make_client("alice@example.com")


@pytest.fixture
def bob(make_client: Callable[[str], TestClient]) -> TestClient:
    """Client logged in as a second user."""
    return make_client("bob@example.com")
