"""DeployRepository on PostgreSQL: ORM rows in, Deploy dataclasses out."""

from typing import cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.errors import AppNotFoundError
from app.deploys.models.deploys import DeployModel
from app.deploys.repositories.deploys import UPDATABLE_FIELDS, Deploy, DeployStatus


# TODO list_for_app in SQL:
#  1. select(DeployModel).where(DeployModel.app_name == app_name)
#  2. if before: .where(tuple_(DeployModel.created_at, DeployModel.id) < tuple_(*before))
#  3. .order_by(DeployModel.created_at.desc(), DeployModel.id.desc()).limit(limit)
#  4. scalars → _to_domain each.
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
        )
        self._session.add(model)
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except IntegrityError:
            # The app was deleted after the caller looked it up (FK on apps.name).
            raise AppNotFoundError(deploy.app_name) from None

        return _to_domain(model)

    async def get(self, deploy_id: str) -> Deploy | None:
        row = await self._session.get(DeployModel, deploy_id)
        return None if row is None else _to_domain(row)

    async def update(self, deploy_id: str, **changes) -> Deploy | None:
        unknown = changes.keys() - UPDATABLE_FIELDS
        if unknown:
            raise TypeError(f"cannot update field(s): {', '.join(sorted(unknown))}")
        result = await self._session.execute(
            update(DeployModel).where(DeployModel.id == deploy_id).values(**changes)
        )

        assert isinstance(result, CursorResult)
        if result.rowcount == 0:
            return None

        row = await self._session.scalar(
            select(DeployModel)
            .where(DeployModel.id == deploy_id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _to_domain(row)

    async def list_all(self) -> list[Deploy]:
        rows = await self._session.scalars(
            select(DeployModel).order_by(DeployModel.created_at)
        )
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
    )
