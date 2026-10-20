"""Subscribers of other domains' events: thin entry points like routers (wired in main.create_app)."""

from app.apps.events import AppDeleted
from app.metrics.services.metrics import MetricsService


async def on_app_deleted(event: AppDeleted, metrics: MetricsService) -> None:
    """An app was deleted: drop its history."""
    await metrics.forget_app(event.name)
