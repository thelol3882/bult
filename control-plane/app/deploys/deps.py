"""Depends wiring of the deploys domain."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.agents.client import Agents
from app.apps.public import AppsFacadeDep
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.core.deps import AgentsDep, RoutesDep, SettingsDep
from app.deploys.services.deploys import DeployService
from app.deploys.uow import DeploysUoW
from app.ingress.routes import RouteWriter


def get_deploys_uow_factory(request: Request) -> Callable[[], DeploysUoW]:
    return request.app.state.deploys_uow_factory


DeployUoWDep = Annotated[Callable[[], DeploysUoW], Depends(get_deploys_uow_factory)]


def build_deploy_service(
    uow_factory: Callable[[], DeploysUoW],
    apps: AppsFacade,
    agents: Agents,
    routes: RouteWriter,
    settings: Settings,
) -> DeployService:
    """The single place DeployService is constructed (request and event paths)."""
    return DeployService(uow_factory, apps, agents, routes, settings)


def get_deploy_service(
    uow_factory: DeployUoWDep,
    apps: AppsFacadeDep,
    agents: AgentsDep,
    routes: RoutesDep,
    settings: SettingsDep,
) -> DeployService:
    return build_deploy_service(uow_factory, apps, agents, routes, settings)


DeployServiceDep = Annotated[DeployService, Depends(get_deploy_service)]
