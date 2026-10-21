"""AppRepository on PostgreSQL: ORM rows in, App dataclasses out."""

from uuid import UUID

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.errors import AppNameTakenError
from app.apps.models.apps import AppModel
from app.apps.repositories.apps import App, AppRoute


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
            health_path=app.health_path,
            owner_id=app.owner_id,
            replicas=app.replicas,
            env=app.env,
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

    async def update(self, name: str, **changes) -> App | None:
        stmt = (
            update(AppModel)
            .where(AppModel.name == name)
            .values(**changes)
            .returning(AppModel)
        )
        result = await self._session.execute(stmt)
        updated_row = result.scalar_one_or_none()

        if updated_row is None:
            return None

        return _to_domain(updated_row)

    async def set_routes(self, name: str, routes: tuple[AppRoute, ...]) -> App | None:
        row = await self._session.scalar(
            update(AppModel)
            .where(AppModel.name == name)
            .values(routes=[{"path": r.path, "app": r.app} for r in routes])
            .returning(AppModel)
        )
        return None if row is None else _to_domain(row)

    async def list_routes(self) -> dict[str, tuple[AppRoute, ...]]:
        rows = await self._session.execute(
            select(AppModel.name, AppModel.routes).where(
                func.jsonb_array_length(AppModel.routes) > 0
            )
        )
        return {name: _routes_to_domain(routes) for name, routes in rows.all()}

    async def remove_routes_to(self, target: str) -> None:
        rows = await self._session.scalars(
            select(AppModel).where(AppModel.routes.contains([{"app": target}]))
        )
        for row in rows.all():
            row.routes = [r for r in row.routes if r["app"] != target]
        await self._session.flush()

    async def count(self, owner_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(AppModel).where(AppModel.owner_id == owner_id)
        )
        return result.scalar_one()

    async def list_stopped(self) -> list[str]:
        rows = await self._session.scalars(
            select(AppModel.name).where(AppModel.replicas == 0).order_by(AppModel.name)
        )
        return list(rows.all())

    async def list(self, owner_id: UUID, offset: int, limit: int) -> list[App]:
        rows = await self._session.scalars(
            select(AppModel)
            .where(AppModel.owner_id == owner_id)
            .order_by(AppModel.name)
            .offset(offset)
            .limit(limit)
        )
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
        health_path=row.health_path,
        owner_id=row.owner_id,
        created_at=row.created_at,
        replicas=row.replicas,
        env=dict(row.env),
        routes=_routes_to_domain(row.routes),
    )


def _routes_to_domain(routes: list[dict[str, str]]) -> tuple[AppRoute, ...]:
    return tuple(AppRoute(path=r["path"], app=r["app"]) for r in routes)
