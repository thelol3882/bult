"""DeployRepository on PostgreSQL: ORM rows in, Deploy dataclasses out."""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, delete, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.errors import AppNotFoundError
from app.deploys.errors import DeployInProgressError
from app.deploys.models.deploys import DeployModel
from app.deploys.repositories.deploys import (
    ACTIVE_STATUSES,
    OWNED_FIELDS,
    UPDATABLE_FIELDS,
    Deploy,
    DeployStatus,
)


class SqlDeployRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, deploy: Deploy) -> Deploy:
        model = DeployModel(
            id=deploy.id,
            app_name=deploy.app_name,
            status=deploy.status,
            commit_sha=deploy.commit_sha,
            image=deploy.image,
            node=deploy.node,
            host_port=deploy.host_port,
            error=deploy.error,
            source_deploy_id=deploy.source_deploy_id,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except IntegrityError as e:
            cause = getattr(e.orig, "__cause__", None)
            constraint_name = getattr(cause, "constraint_name", None)

            if constraint_name == "uq_deploys_app_active":
                raise DeployInProgressError(deploy.app_name) from None

            if constraint_name == "fk_deploys_app_name_apps":
                raise AppNotFoundError(deploy.app_name) from None

            raise

        return _to_domain(model)

    async def get(self, deploy_id: str) -> Deploy | None:
        row = await self._session.get(DeployModel, deploy_id)
        return None if row is None else _to_domain(row)

    async def update(self, deploy_id: str, **changes) -> Deploy | None:
        return await self._update(deploy_id, changes, UPDATABLE_FIELDS)

    async def _update(
        self,
        deploy_id: str,
        changes: dict,
        allowed: set[str],
        owner: str | None = None,
    ) -> Deploy | None:
        unknown = changes.keys() - allowed
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        stmt = update(DeployModel).where(DeployModel.id == deploy_id)
        if owner is not None:
            stmt = stmt.where(DeployModel.lease_owner == owner)
        result = await self._session.execute(stmt.values(**changes))

        assert isinstance(result, CursorResult)
        if result.rowcount == 0:
            return None

        row = await self._session.scalar(
            select(DeployModel)
            .where(DeployModel.id == deploy_id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _to_domain(row)

    async def claim(self, owner: str, lease: timedelta, now: datetime) -> Deploy | None:
        stmt = (
            select(DeployModel)
            .where(
                DeployModel.status.in_(ACTIVE_STATUSES),
                or_(
                    DeployModel.lease_until.is_(None),
                    DeployModel.lease_until < now,
                ),
            )
            .order_by(DeployModel.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        row = await self._session.scalar(stmt)
        if row is None:
            return None

        row.lease_owner = owner
        row.lease_until = now + lease
        row.attempts = (row.attempts or 0) + 1

        await self._session.flush()

        return _to_domain(row)

    async def renew(
        self, deploy_id: str, owner: str, lease: timedelta, now: datetime
    ) -> bool:
        result = await self._session.execute(
            update(DeployModel)
            .where(DeployModel.id == deploy_id, DeployModel.lease_owner == owner)
            .values(lease_until=now + lease)
        )
        assert isinstance(result, CursorResult)
        return result.rowcount == 1

    async def update_owned(
        self, deploy_id: str, owner: str, **changes
    ) -> Deploy | None:
        return await self._update(deploy_id, changes, OWNED_FIELDS, owner=owner)

    async def list_all(self) -> list[Deploy]:
        rows = await self._session.scalars(
            select(DeployModel).order_by(DeployModel.created_at)
        )
        result: list[Deploy] = []
        for row in rows.all():
            result.append(_to_domain(row))

        return result

    async def list_running(self, app_name: str) -> list[Deploy]:
        rows = await self._session.scalars(
            select(DeployModel)
            .where(DeployModel.app_name == app_name, DeployModel.status == "running")
            .order_by(DeployModel.created_at.desc(), DeployModel.id.desc())
        )
        return [_to_domain(row) for row in rows.all()]

    async def latest_restorable(self, app_name: str) -> Deploy | None:
        row = await self._session.scalar(
            select(DeployModel)
            .where(
                DeployModel.app_name == app_name,
                DeployModel.image != "",
                DeployModel.node != "",
            )
            .order_by(DeployModel.created_at.desc(), DeployModel.id.desc())
            .limit(1)
        )
        return None if row is None else _to_domain(row)

    async def list_for_app(
        self, app_name: str, before: tuple[datetime, str] | None, limit: int
    ) -> list[Deploy]:
        stmt = select(DeployModel).where(DeployModel.app_name == app_name)
        if before:
            stmt = stmt.where(
                tuple_(DeployModel.created_at, DeployModel.id) < tuple_(*before)
            )

        stmt = stmt.order_by(
            DeployModel.created_at.desc(), DeployModel.id.desc()
        ).limit(limit)

        rows = await self._session.scalars(stmt)
        result: list[Deploy] = []
        for row in rows.all():
            result.append(_to_domain(row))

        return result

    async def delete_for_app(self, app_name: str) -> None:
        await self._session.execute(
            delete(DeployModel).where(DeployModel.app_name == app_name)
        )


def _to_domain(row: DeployModel) -> Deploy:
    return Deploy(
        id=row.id,
        app_name=row.app_name,
        status=cast(DeployStatus, row.status),
        commit_sha=row.commit_sha,
        image=row.image,
        node=row.node,
        host_port=row.host_port,
        error=row.error,
        created_at=row.created_at,
        lease_owner=row.lease_owner,
        lease_until=row.lease_until,
        attempts=row.attempts,
        source_deploy_id=row.source_deploy_id,
    )
