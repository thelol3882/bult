"""Shared fixtures: pytest picks this file up for every test in tests/."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_app_store
from app.main import create_app
from app.services.apps import AppStore


@pytest.fixture
def store() -> AppStore:
    """A fresh in-memory store for every test."""
    return AppStore()


@pytest.fixture
def app(store: AppStore):
    """A fresh FastAPI application with the store dependency overridden."""
    application = create_app()
    application.dependency_overrides[get_app_store] = lambda: store
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Synchronous test client: calls the app in-process, no server needed."""
    return TestClient(app)
