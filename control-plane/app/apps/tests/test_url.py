"""The app URL comes from settings."""

from datetime import UTC, datetime

from app.apps.repositories.apps import App, InMemoryAppRepository
from app.apps.services.apps import AppService
from app.core.config import Settings
from app.core.events import EventBus, EventCollector


def make_settings(**overrides) -> Settings:
    values = {"builder": "b:1", "runners": {}, "trusted_proxy": "10.0.0.1"} | overrides
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
    service = AppService(InMemoryAppRepository(), settings, EventCollector(EventBus()))

    assert service.url(make_app("blog")) == "http://blog.example.test"


def test_app_url_defaults_to_plain_http():
    service = AppService(InMemoryAppRepository(), make_settings(), EventCollector(EventBus()))

    assert service.url(make_app("blog")) == "http://blog.bult.localhost"
