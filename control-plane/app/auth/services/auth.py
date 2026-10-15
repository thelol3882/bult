"""Auth domain rules: register, log in, resolve a token to a Principal."""

from collections.abc import Callable
from uuid import UUID

from app.auth.errors import InvalidCredentialsError, NotAuthenticatedError
from app.auth.repositories.users import User
from app.auth.schemas.auth import LoginIn, RegisterIn
from app.auth.services.passwords import PasswordHasher
from app.auth.services.tokens import InvalidTokenError, TokenIssuer
from app.auth.uow import AuthUoW
from app.core.principal import Principal


class AuthService:
    def __init__(
        self,
        uow_factory: Callable[[], AuthUoW],
        hasher: PasswordHasher,
        tokens: TokenIssuer,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._tokens = tokens

    async def register(self, data: RegisterIn) -> User:
        email = data.email.lower()
        password_hash = await self._hasher.hash(data.password)

        async with self._uow_factory() as uow:
            user = await uow.users.add(User(email=email, password_hash=password_hash))
            await uow.commit()
            return user

    async def login(self, data: LoginIn) -> str:
        """Access token, or InvalidCredentialsError."""
        email = data.email.lower()

        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(email)

        if user is None:
            await self._hasher.burn(data.password)
            raise InvalidCredentialsError()

        ok, new_hash = await self._hasher.verify(data.password, user.password_hash)
        if not ok:
            raise InvalidCredentialsError()

        if new_hash is not None and user.id is not None:
            async with self._uow_factory() as uow:
                await uow.users.set_password_hash(user.id, new_hash)
                await uow.commit()

        assert user.id is not None
        return self._tokens.issue(user.id)

    async def authenticate(self, token: str) -> Principal:
        """Principal of a valid token whose user still exists, else NotAuthenticatedError."""
        try:
            user_id = self._tokens.user_id(token)
        except InvalidTokenError:
            raise NotAuthenticatedError() from None

        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None or user.id is None:
                raise NotAuthenticatedError()

        return Principal(id=user.id, email=user.email)

    async def get_user(self, user_id: UUID) -> User:
        """Fetch the full User entity or fail if deleted after token verification."""
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise NotAuthenticatedError()
            return user
