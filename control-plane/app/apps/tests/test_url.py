"""The app URL comes from settings."""

from datetime import UTC, datetime

from app.apps.repositories.apps import App
from app.apps.services.apps import AppService
from app.apps.uow import InMemoryAppsUoW
from app.core.config import Settings
from app.core.events import EventBus, EventCollector


def make_settings(**overrides) -> Settings:
    values = {
        "builder": "b:1",
        "runners": {},
        "trusted_proxy": "10.0.0.1",
        "database_url": "postgresql+asyncpg://test/test",
    } | overrides
    return Settings(**values)


def make_app(name: str) -> App:
    return App(
        name=name,
        preset="fastapi",
        repo_url="https://github.com/example/blog.git",
        branch="main",
        subdir="",
        created_at=datetime.now(UTC),
    )


def test_app_url_comes_from_settings():
    settings = make_settings(apps_scheme="http", apps_domain="example.test")
    uow = InMemoryAppsUoW()
    service = AppService(
        uow_factory=lambda: uow, settings=settings, events=EventCollector(EventBus())
    )

    assert service.url(make_app("blog")) == "http://blog.example.test"


def test_app_url_defaults_to_plain_http():
    uow = InMemoryAppsUoW()
    service = AppService(
        uow_factory=lambda: uow,
        settings=make_settings(),
        events=EventCollector(EventBus()),
    )

    assert service.url(make_app("blog")) == "http://blog.bult.localhost"
