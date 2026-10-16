"""Deploy storage behind a Protocol.

Lifecycle: queued → building → starting → running; any active status → failed.
Active deploys are the work queue: a worker claims one under a lease.
"""

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.deploys.errors import DeployInProgressError

DeployStatus = Literal["queued", "building", "starting", "running", "failed"]
ACTIVE_STATUSES: tuple[DeployStatus, ...] = ("queued", "building", "starting")


@dataclass
class Deploy:
    """One build-and-run of an app; mutable, the background task advances it."""

    id: str
    app_name: str
    status: DeployStatus = "queued"
    commit_sha: str = ""
    image: str = ""  # "repository@digest" once the build succeeded
    node: str = ""
    host_port: int = 0
    error: str = ""  # user-facing
    created_at: datetime | None = None  # set by storage on add
    lease_owner: str = ""  # worker id holding the lease
    lease_until: datetime | None = None
    attempts: int = 0  # claims so far


LEASE_FIELDS = {"lease_owner", "lease_until", "attempts"}
UPDATABLE_FIELDS = (
    {f.name for f in fields(Deploy)} - {"id", "app_name", "created_at"} - LEASE_FIELDS
)
# The lease holder may also release the lease (lease_until=None) and give back the attempt.
OWNED_FIELDS = UPDATABLE_FIELDS | {"lease_until", "attempts"}


class DeployRepository(Protocol):
    """Storage only; domain rules live in DeployService."""

    async def add(self, deploy: Deploy) -> Deploy: ...
    async def get(self, deploy_id: str) -> Deploy | None: ...
    async def update(self, deploy_id: str, **changes) -> Deploy | None:
        """Change fields; None if the deploy is gone."""
        ...

    async def claim(
        self, owner: str, lease: timedelta, now: datetime
    ) -> Deploy | None:
        """Oldest active deploy whose lease is empty or expired, now leased to `owner`
        (attempts + 1); None if there is none. Two concurrent claims never get the same deploy."""
        ...

    async def renew(
        self, deploy_id: str, owner: str, lease: timedelta, now: datetime
    ) -> bool:
        """Extend the lease; False if `owner` no longer holds it."""
        ...

    async def update_owned(
        self, deploy_id: str, owner: str, **changes
    ) -> Deploy | None:
        """`update` (plus lease_until, attempts), but only while `owner` holds the lease
        (fencing); None if the deploy is gone or the lease is held by someone else."""
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
        if deploy.status in ACTIVE_STATUSES and any(
            d.app_name == deploy.app_name and d.status in ACTIVE_STATUSES
            for d in self._deploys.values()
        ):  # what the partial unique index does in Postgres
            raise DeployInProgressError(deploy.app_name)
        stored = replace(deploy, created_at=datetime.now(UTC))
        self._deploys[deploy.id] = stored
        return replace(stored)

    async def get(self, deploy_id: str) -> Deploy | None:
        deploy = self._deploys.get(deploy_id)
        return None if deploy is None else replace(deploy)

    async def update(self, deploy_id: str, **changes) -> Deploy | None:
        return self._update(deploy_id, changes, UPDATABLE_FIELDS, owner=None)

    def _update(
        self, deploy_id: str, changes: dict, allowed: set[str], owner: str | None
    ) -> Deploy | None:
        unknown = changes.keys() - allowed
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        deploy = self._deploys.get(deploy_id)
        if deploy is None or (owner is not None and deploy.lease_owner != owner):
            return None
        self._deploys[deploy_id] = deploy = replace(deploy, **changes)
        return replace(deploy)

    async def claim(
        self, owner: str, lease: timedelta, now: datetime
    ) -> Deploy | None:
        candidates = [
            d
            for d in self._deploys.values()
            if d.status in ACTIVE_STATUSES
            and (d.lease_until is None or d.lease_until < now)
        ]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda d: (d.created_at, d.id))
        self._deploys[oldest.id] = claimed = replace(
            oldest,
            lease_owner=owner,
            lease_until=now + lease,
            attempts=oldest.attempts + 1,
        )
        return replace(claimed)

    async def renew(
        self, deploy_id: str, owner: str, lease: timedelta, now: datetime
    ) -> bool:
        deploy = self._deploys.get(deploy_id)
        if deploy is None or deploy.lease_owner != owner:
            return False
        self._deploys[deploy_id] = replace(deploy, lease_until=now + lease)
        return True

    async def update_owned(
        self, deploy_id: str, owner: str, **changes
    ) -> Deploy | None:
        return self._update(deploy_id, changes, OWNED_FIELDS, owner=owner)

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
