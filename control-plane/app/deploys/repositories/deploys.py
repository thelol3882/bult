"""Deploy storage behind a Protocol (in-memory until PostgreSQL storage lands).

Lifecycle: building → starting → running; building or starting → failed.
"""

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import Literal, Protocol

DeployStatus = Literal["building", "starting", "running", "failed"]


@dataclass
class Deploy:
    """One build-and-run of an app; mutable, the background task advances it."""

    id: str
    app_name: str
    status: DeployStatus = "building"
    commit_sha: str = ""
    image: str = ""  # "repository@digest" once the build succeeded
    node: str = ""
    host_port: int = 0
    error: str = ""  # user-facing
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


_UPDATABLE = {f.name for f in fields(Deploy)} - {"id", "app_name", "created_at"}


class DeployRepository(Protocol):
    """Storage only; domain rules live in DeployService."""

    def add(self, deploy: Deploy) -> Deploy: ...
    def get(self, deploy_id: str) -> Deploy | None: ...
    def update(self, deploy_id: str, **changes) -> Deploy | None:
        """Change fields; None if the deploy is gone."""
        ...

    def list_all(self) -> list[Deploy]: ...
    def delete_for_app(self, app_name: str) -> None: ...


class InMemoryDeployRepository:
    """Dict keyed by id; also the test fake."""

    def __init__(self) -> None:
        self._deploys: dict[str, Deploy] = {}

    def add(self, deploy: Deploy) -> Deploy:
        if deploy.id in self._deploys:
            raise ValueError(f"deploy {deploy.id} already exists")
        self._deploys[deploy.id] = deploy
        return deploy

    def get(self, deploy_id: str) -> Deploy | None:
        return self._deploys.get(deploy_id)

    def update(self, deploy_id: str, **changes) -> Deploy | None:
        """No lock needed: single event loop, no await inside."""
        unknown = changes.keys() - _UPDATABLE
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        deploy = self._deploys.get(deploy_id)
        if deploy is None:
            return None
        for name, value in changes.items():
            setattr(deploy, name, value)
        return deploy

    def list_all(self) -> list[Deploy]:
        return list(self._deploys.values())

    def delete_for_app(self, app_name: str) -> None:
        self._deploys = {
            k: d for k, d in self._deploys.items() if d.app_name != app_name
        }
