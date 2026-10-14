"""Depends wiring of the auth domain; CurrentUser is what other domains' routers import."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.errors import NotAuthenticatedError
from app.auth.services.auth import AuthService
from app.auth.services.passwords import PasswordHasher
from app.auth.services.tokens import TokenIssuer
from app.auth.uow import AuthUoW
from app.core.deps import SettingsDep
from app.core.principal import Principal

bearer = HTTPBearer(auto_error=False)


def get_auth_uow_factory(request: Request) -> Callable[[], AuthUoW]:
    return request.app.state.auth_uow_factory


def get_password_hasher(request: Request) -> PasswordHasher:
    return request.app.state.password_hasher


def get_token_issuer(request: Request) -> TokenIssuer:
    return request.app.state.token_issuer


def get_token_ttl(settings: SettingsDep) -> int:
    return settings.jwt_ttl_seconds


TokenTTLDep = Annotated[int, Depends(get_token_ttl)]


def get_auth_service(
    uow_factory: Annotated[Callable[[], AuthUoW], Depends(get_auth_uow_factory)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    tokens: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> AuthService:
    return AuthService(
        uow_factory=uow_factory,
        hasher=hasher,
        tokens=tokens,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: AuthServiceDep,
) -> Principal:
    if credentials is None:
        raise NotAuthenticatedError()

    return await service.authenticate(credentials.credentials)


CurrentUser = Annotated[Principal, Depends(get_current_user)]
