"""Dependencies shared by the routers (Depends targets)."""

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.services.agent_client import AgentClients
from app.services.apps import AppStore
from app.services.deploys import DeployStore
from app.services.nginx import RouteWriter


def get_app_store(request: Request) -> AppStore:
    """The app store of the running application (overridden in tests)."""
    return request.app.state.app_store


def get_deploy_store(request: Request) -> DeployStore:
    """The deploy store of the running application (overridden in tests)."""
    return request.app.state.deploy_store


def get_agents(request: Request) -> AgentClients:
    """gRPC clients to the node agents, created in the lifespan (overridden in tests)."""
    return request.app.state.agents


def get_settings(request: Request) -> Settings:
    """Settings loaded once at startup."""
    return request.app.state.settings


def get_routes(request: Request) -> RouteWriter:
    """The ingress route writer, created at startup (overridden in tests)."""
    return request.app.state.routes


AppStoreDep = Annotated[AppStore, Depends(get_app_store)]
DeployStoreDep = Annotated[DeployStore, Depends(get_deploy_store)]
AgentsDep = Annotated[AgentClients, Depends(get_agents)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RoutesDep = Annotated[RouteWriter, Depends(get_routes)]
