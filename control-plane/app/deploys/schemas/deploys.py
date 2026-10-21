"""Pydantic schemas of the deploys resource."""

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import MAX_REPLICAS
from app.deploys.repositories.deploys import DeployStatus


class ReplicaOut(BaseModel):
    """One container of a deploy. `unhealthy`: it fails its health check or its node stopped
    reporting; `crashloop`: replacing it did not help, it waits for a new deploy or a scale;
    `lost`: its node is dead and a replacement is being placed."""

    model_config = ConfigDict(from_attributes=True)

    index: int
    node: str
    host_port: int
    status: Literal["running", "unhealthy", "exited", "oom", "crashloop", "lost"]
    exit_code: int | None  # of the last death
    recent_failures: int  # deaths in the last 10 minutes
    reason: str  # why it is not serving, "" while it is
    log_tail: list[str]  # the app's last output at its last death
    retry_at: datetime | None  # when a dead replica is replaced


class DeployOut(BaseModel):
    """A deploy as the API returns it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    app_name: str
    status: DeployStatus
    commit_sha: str
    image: str
    desired_replicas: int
    ready_replicas: int  # replicas that run and are healthy, on ready nodes: shown as ready/desired
    replicas: list[ReplicaOut]  # the running ones
    error: str
    created_at: datetime
    source_deploy_id: str
    restorable: bool  # a rollback or start can reuse its image


class LogsOut(BaseModel):
    """The tail of the output of one replica of the app's running deploy."""

    deploy_id: str | None  # None when no deploy is running
    replica: int | None  # index of the replica the lines come from
    lines: list[str]


class ReplicasUpdate(BaseModel):
    """Request body of PUT /apps/{name}/replicas."""

    model_config = ConfigDict(extra="forbid")

    replicas: int = Field(ge=0, le=MAX_REPLICAS)


class ReplicasOut(BaseModel):
    """The new desired count and the deploy it applies to (None when the app is stopped)."""

    replicas: int
    deploy: DeployOut | None
