"""Deploy storage behind a Protocol.

Lifecycle: queued → building → starting → running; any active status → failed;
queued or building → cancelled (the user's cancel).
A deploy created from an earlier image starts at `starting`. A running deploy ends as
`superseded` (a newer one took over) or `stopped` (the app was stopped).
Active deploys are the work queue: a worker claims one under a lease.
"""

from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.deploys.errors import DeployInProgressError
from app.deploys.repositories.replicas import InMemoryReplicaRepository, ReplicaView

DeployStatus = Literal[
    "queued",
    "building",
    "starting",
    "running",
    "failed",
    "cancelled",
    "superseded",
    "stopped",
]
ACTIVE_STATUSES: tuple[DeployStatus, ...] = ("queued", "building", "starting")


@dataclass
class Deploy:
    """One build-and-run of an app; mutable, the background task advances it."""

    id: str
    app_name: str
    status: DeployStatus = "queued"
    commit_sha: str = ""
    image: str = ""  # "repository@digest" once the build succeeded
    desired_replicas: int = 1
    ran: bool = False  # reached `running` at some point
    error: str = ""  # user-facing
    created_at: datetime | None = None  # set by storage on add
    lease_owner: str = ""  # worker id holding the lease
    lease_until: datetime | None = None
    attempts: int = 0  # claims so far
    source_deploy_id: str = ""  # set when the deploy reuses that deploy's image
    # Not stored in the deploys table: DeployService fills them in when it reads.
    ready_replicas: int = 0
    replicas: tuple[ReplicaView, ...] = field(default=(), repr=False)

    @property
    def restorable(self) -> bool:
        """It has an image and ran at some point."""
        return bool(self.image) and self.ran


LEASE_FIELDS = {"lease_owner", "lease_until", "attempts"}
NOT_STORED = {"ready_replicas", "replicas"}
UPDATABLE_FIELDS = (
    {f.name for f in fields(Deploy)}
    - {"id", "app_name", "created_at"}
    - LEASE_FIELDS
    - NOT_STORED
)
# The lease holder may also release the lease and give back the attempt.
OWNED_FIELDS = UPDATABLE_FIELDS | {"lease_owner", "lease_until", "attempts"}


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

    async def cancel_queued(self, deploy_id: str, now: datetime) -> Deploy | None:
        """queued → cancelled, only if the deploy is still queued and no worker holds a live
        lease on it (one claimed but not yet building counts as taken). None if it no longer
        matches. The lease is cleared."""
        ...

    async def list_all(self) -> list[Deploy]: ...
    async def list_running(self, app_name: str) -> list[Deploy]:
        """The app's deploys in status `running`, newest first."""
        ...

    async def latest_restorable(self, app_name: str) -> Deploy | None:
        """The app's newest deploy that has an image and ran at some point."""
        ...

    async def delete_for_app(self, app_name: str) -> None: ...
    async def list_for_app(
        self, app_name: str, before: tuple[datetime, str] | None, limit: int
    ) -> list[Deploy]: ...


class InMemoryDeployRepository:
    """Dict keyed by id; also the test fake. Hands out copies, like rows from a database."""

    def __init__(self, replicas: InMemoryReplicaRepository | None = None) -> None:
        self._deploys: dict[str, Deploy] = {}
        self._replicas = replicas  # emptied together with the deploys, like the cascade

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

    async def cancel_queued(self, deploy_id: str, now: datetime) -> Deploy | None:
        deploy = self._deploys.get(deploy_id)
        if (
            deploy is None
            or deploy.status != "queued"
            or (deploy.lease_until is not None and deploy.lease_until >= now)
        ):
            return None
        self._deploys[deploy_id] = deploy = replace(
            deploy, status="cancelled", lease_owner="", lease_until=None
        )
        return replace(deploy)

    async def list_all(self) -> list[Deploy]:
        return [replace(d) for d in self._deploys.values()]

    async def list_running(self, app_name: str) -> list[Deploy]:
        running = [
            d
            for d in self._deploys.values()
            if d.app_name == app_name and d.status == "running"
        ]
        running.sort(key=lambda d: (d.created_at, d.id), reverse=True)
        return [replace(d) for d in running]

    async def latest_restorable(self, app_name: str) -> Deploy | None:
        candidates = [
            d
            for d in self._deploys.values()
            if d.app_name == app_name and d.restorable
        ]
        if not candidates:
            return None
        return replace(max(candidates, key=lambda d: (d.created_at, d.id)))

    async def list_for_app(
        self, app_name: str, before: tuple[datetime, str] | None, limit: int
    ) -> list[Deploy]:
        deploys = [d for d in self._deploys.values() if d.app_name == app_name]
        deploys.sort(key=lambda d: (d.created_at, d.id), reverse=True)
        if before is not None:
            deploys = list(filter(lambda d: (d.created_at, d.id) < before, deploys))

        return [replace(d) for d in deploys[:limit]]

    async def delete_for_app(self, app_name: str) -> None:
        if self._replicas is not None:
            self._replicas.forget_deploys(
                d.id for d in self._deploys.values() if d.app_name == app_name
            )
        self._deploys = {
            k: d for k, d in self._deploys.items() if d.app_name != app_name
        }
