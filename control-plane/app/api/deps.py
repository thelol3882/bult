"""Dependencies shared by the routers (Depends targets)."""

from typing import Annotated

from fastapi import Depends, Request

from app.services.apps import AppStore


def get_app_store(request: Request) -> AppStore:
    """The app store of the running application (overridden in tests)."""
    return request.app.state.app_store


AppStoreDep = Annotated[AppStore, Depends(get_app_store)]
