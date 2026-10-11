"""In-memory deploy store. Replaced by PostgreSQL in lesson 18 (like AppStore).

A deploy = one "build + run" of an app:
    building → starting → running
        └──────────┴──────→ failed
"""

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import Literal

DeployStatus = Literal["building", "starting", "running", "failed"]


@dataclass
class Deploy:
    """One deploy of an app. Mutable: the background task moves it along."""

    id: str
    app_name: str
    status: DeployStatus = "building"
    commit_sha: str = ""
    image: str = ""  # "repository@digest" once the build succeeded
    node: str = ""
    host_port: int = 0
    error: str = ""  # user-facing, no internal paths or stack traces
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


_UPDATABLE = {f.name for f in fields(Deploy)} - {"id", "app_name", "created_at"}


class DeployNotFoundError(Exception):
    """No deploy with this id for this app (→ HTTP 404)."""


class DeployStore:
    """Deploys kept in a dict, keyed by id."""

    def __init__(self) -> None:
        self._deploys: dict[str, Deploy] = {}

    def add(self, deploy: Deploy) -> Deploy:
        if deploy.id in self._deploys:
            raise ValueError(f"deploy {deploy.id} already exists")
        self._deploys[deploy.id] = deploy
        return deploy

    def get(self, app_name: str, deploy_id: str) -> Deploy:
        """DeployNotFoundError if missing OR if it belongs to another app."""
        deploy = self._deploys.get(deploy_id)
        if deploy is None or deploy.app_name != app_name:
            raise DeployNotFoundError(deploy_id)
        return deploy

    def update(self, deploy_id: str, **changes) -> Deploy:
        """Change fields of a deploy (status, node, host_port, error…).

        Only the background task calls it. Single event loop + no await
        inside → no lock needed.
        """
        deploy = self._deploys.get(deploy_id)
        if deploy is None:
            raise DeployNotFoundError(deploy_id)
        unknown = changes.keys() - _UPDATABLE
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        for name, value in changes.items():
            setattr(deploy, name, value)
        return deploy

    def all(self) -> list[Deploy]:
        """Every deploy of every app."""
        return list(self._deploys.values())

    def remove_app(self, app_name: str) -> None:
        """Forget every deploy of an app (called when the app is deleted)."""
        self._deploys = {
            k: d for k, d in self._deploys.items() if d.app_name != app_name
        }
