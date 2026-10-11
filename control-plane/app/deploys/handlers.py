"""Subscribers of other domains' events: thin entry points like routers (wired in main.create_app)."""

from app.apps.events import AppDeleted
from app.deploys.services.deploys import DeployService


async def on_app_deleted(event: AppDeleted, deploys: DeployService) -> None:
    """An app was deleted: let the deploys service clean up."""
    await deploys.remove_app(event.name)
