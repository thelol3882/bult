"""Deploy storage behind a Protocol.

Lifecycle: building → starting → running; building or starting → failed.
"""

from dataclasses import dataclass, fields, replace
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
    created_at: datetime | None = None  # set by storage on add


UPDATABLE_FIELDS = {f.name for f in fields(Deploy)} - {"id", "app_name", "created_at"}


class DeployRepository(Protocol):
    """Storage only; domain rules live in DeployService."""

    async def add(self, deploy: Deploy) -> Deploy: ...
    async def get(self, deploy_id: str) -> Deploy | None: ...
    async def update(self, deploy_id: str, **changes) -> Deploy | None:
        """Change fields; None if the deploy is gone."""
        ...

    async def list_all(self) -> list[Deploy]: ...
    async def delete_for_app(self, app_name: str) -> None: ...
    async def list_for_app(
        self, app_name: str, before: tuple[datetime, str] | None, limit: int
    ) -> list[Deploy]: ...


class InMemoryDeployRepository:
    """Dict keyed by id; also the test fake. Hands out copies, like rows from a database."""

    def __init__(self) -> None:
        self._deploys: dict[str, Deploy] = {}

    async def add(self, deploy: Deploy) -> Deploy:
        if deploy.id in self._deploys:
            raise ValueError(f"deploy {deploy.id} already exists")
        stored = replace(deploy, created_at=datetime.now(UTC))
        self._deploys[deploy.id] = stored
        return replace(stored)

    async def get(self, deploy_id: str) -> Deploy | None:
        deploy = self._deploys.get(deploy_id)
        return None if deploy is None else replace(deploy)

    async def update(self, deploy_id: str, **changes) -> Deploy | None:
        unknown = changes.keys() - UPDATABLE_FIELDS
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        deploy = self._deploys.get(deploy_id)
        if deploy is None:
            return None
        self._deploys[deploy_id] = deploy = replace(deploy, **changes)
        return replace(deploy)

    async def list_all(self) -> list[Deploy]:
        return [replace(d) for d in self._deploys.values()]

    async def list_for_app(
        self, app_name: str, before: tuple[datetime, str] | None, limit: int
    ) -> list[Deploy]:
        deploys = [d for d in self._deploys.values() if d.app_name == app_name]
        deploys.sort(key=lambda d: (d.created_at, d.id), reverse=True)
        if before is not None:
            deploys = list(filter(lambda d: (d.created_at, d.id) < before, deploys))

        return [replace(d) for d in deploys[:limit]]

    async def delete_for_app(self, app_name: str) -> None:
        self._deploys = {
            k: d for k, d in self._deploys.items() if d.app_name != app_name
        }
