"""Depends wiring of the deploys domain."""

import asyncio
from typing import Annotated

from fastapi import Depends, Request

from app.agents.client import Agents
from app.apps.public import AppsFacadeDep
from app.apps.services.facade import AppsFacade
from app.core.config import Settings
from app.core.deps import AgentsDep, RoutesDep, SettingsDep
from app.deploys.repositories.deploys import DeployRepository
from app.deploys.services.deploys import DeployService
from app.ingress.routes import RouteWriter


def get_deploy_repo(request: Request) -> DeployRepository:
    """The deploy repository."""
    return request.app.state.deploy_repo


def get_deploy_tasks(request: Request) -> set[asyncio.Task[None]]:
    """Running run_deploy tasks."""
    return request.app.state.deploy_tasks


DeployRepoDep = Annotated[DeployRepository, Depends(get_deploy_repo)]
DeployTasksDep = Annotated[set[asyncio.Task[None]], Depends(get_deploy_tasks)]


def build_deploy_service(
    repo: DeployRepository,
    apps: AppsFacade,
    agents: Agents,
    routes: RouteWriter,
    settings: Settings,
    tasks: set[asyncio.Task[None]],
) -> DeployService:
    """The single place DeployService is constructed (request and event paths)."""
    return DeployService(repo, apps, agents, routes, settings, tasks)


def get_deploy_service(
    repo: DeployRepoDep,
    apps: AppsFacadeDep,
    agents: AgentsDep,
    routes: RoutesDep,
    settings: SettingsDep,
    tasks: DeployTasksDep,
) -> DeployService:
    return build_deploy_service(repo, apps, agents, routes, settings, tasks)


DeployServiceDep = Annotated[DeployService, Depends(get_deploy_service)]
