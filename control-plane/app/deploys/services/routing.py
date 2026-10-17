"""Which apps answer with the "stopped" page when routes are rendered."""

from app.apps.services.facade import AppsFacade
from app.ingress.routes import Route


async def stopped_apps(
    apps: AppsFacade, routes: list[Route], skip_app: str | None = None
) -> list[str]:
    """Stopped apps that have no route: a running deploy wins over the flag."""
    live = {r.name for r in routes}
    return [
        name
        for name in await apps.stopped_app_names()
        if name not in live and name != skip_app
    ]
