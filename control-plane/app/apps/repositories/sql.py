"""AppRepository on PostgreSQL: ORM rows in, App dataclasses out."""

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.errors import AppNameTakenError
from app.apps.models.apps import AppModel
from app.apps.repositories.apps import App


class SqlAppRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, app: App) -> App:
        model = AppModel(
            name=app.name,
            preset=app.preset,
            branch=app.branch,
            repo_url=app.repo_url,
            subdir=app.subdir,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except IntegrityError:
            raise AppNameTakenError(app.name) from None

        return _to_domain(model)

    async def get(self, name: str) -> App | None:
        row = await self._session.scalar(select(AppModel).where(AppModel.name == name))
        return None if row is None else _to_domain(row)

    async def list(self) -> list[App]:
        rows = await self._session.scalars(select(AppModel).order_by(AppModel.name))
        result: list[App] = []
        for row in rows.all():
            result.append(_to_domain(row))

        return result

    async def delete(self, name: str) -> bool:
        result = await self._session.execute(
            delete(AppModel).where(AppModel.name == name)
        )

        assert isinstance(result, CursorResult)
        return result.rowcount > 0


def _to_domain(row: AppModel) -> App:
    return App(
        id=row.id,
        name=row.name,
        preset=row.preset,
        repo_url=row.repo_url,
        branch=row.branch,
        subdir=row.subdir,
        created_at=row.created_at,
    )
