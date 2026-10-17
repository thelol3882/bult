"""Pydantic schemas of the deploys resource."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.deploys.repositories.deploys import DeployStatus


class DeployOut(BaseModel):
    """A deploy as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    app_name: str
    status: DeployStatus
    commit_sha: str
    image: str
    node: str
    host_port: int
    error: str
    created_at: datetime
    source_deploy_id: str
    restorable: bool  # a rollback or start can reuse its image


class LogsOut(BaseModel):
    """The tail of the output of the app's running replica."""

    deploy_id: str | None  # None when no deploy is running
    lines: list[str]
