"""User storage behind a Protocol."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from app.auth.errors import EmailTakenError


@dataclass(frozen=True)
class User:
    email: str
    password_hash: str
    id: UUID | None = None
    created_at: datetime | None = None


class UserRepository(Protocol):
    async def add(self, user: User) -> User:
        """EmailTakenError if the email exists."""
        ...

    async def get_by_email(self, email: str) -> User | None: ...
    async def get(self, user_id: UUID) -> User | None: ...
    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None: ...


class InMemoryUserRepository:
    """Dict keyed by email; also the test fake."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def add(self, user: User) -> User:
        if user.email in self.users:
            raise EmailTakenError(user.email)

        persisted_user = replace(
            user,
            id=uuid7(),
            created_at=datetime.now(UTC),
        )
        self.users[persisted_user.email] = persisted_user
        return persisted_user

    async def get_by_email(self, email: str) -> User | None:
        return self.users.get(email)

    async def get(self, user_id: UUID) -> User | None:
        for user in self.users.values():
            if user.id == user_id:
                return user
        return None

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        for email, user in self.users.items():
            if user.id == user_id:
                self.users[email] = replace(user, password_hash=password_hash)
                return
