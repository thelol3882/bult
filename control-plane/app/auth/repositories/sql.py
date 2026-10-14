"""UserRepository on PostgreSQL: ORM rows in, User dataclasses out."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import EmailTakenError
from app.auth.models.users import UserModel
from app.auth.repositories.users import User


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        model = UserModel(email=user.email, password_hash=user.password_hash)
        self._session.add(model)
        try:
            await self._session.flush()
            await self._session.refresh(model)
        except IntegrityError:
            raise EmailTakenError(user.email) from None

        return _to_domain(model)

    async def get_by_email(self, email: str) -> User | None:
        row = await self._session.scalar(
            select(UserModel).where(UserModel.email == email)
        )
        return None if row is None else _to_domain(row)

    async def get(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserModel, user_id)
        return None if row is None else _to_domain(row)

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        stmt = (
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(password_hash=password_hash)
        )
        await self._session.execute(stmt)
        await self._session.flush()


def _to_domain(row: UserModel) -> User:
    return User(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        created_at=row.created_at,
    )
