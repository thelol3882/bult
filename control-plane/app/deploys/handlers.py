"""Subscribers of other domains' events: thin entry points like routers (wired in main.create_app)."""

from app.apps.events import AppDeleted, AppRoutesChanged
from app.deploys.services.deploys import DeployService


async def on_app_deleted(event: AppDeleted, deploys: DeployService) -> None:
    """An app was deleted: let the deploys service clean up."""
    await deploys.remove_app(event.name)


async def on_app_routes_changed(event: AppRoutesChanged, deploys: DeployService) -> None:
    """The path routes of an app changed: re-apply the ingress routes."""
    _ = await deploys.reapply_routes(f"routes of {event.name}")
