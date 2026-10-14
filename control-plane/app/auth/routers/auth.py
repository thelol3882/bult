"""Auth resource: register, login, me."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.auth.deps import AuthServiceDep, CurrentUser, TokenTTLDep
from app.auth.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterIn,
    service: AuthServiceDep,
) -> UserOut:
    user = await service.register(payload)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=TokenOut,
    status_code=status.HTTP_200_OK,
)
async def login(
    payload: LoginIn,
    service: AuthServiceDep,
    jwt_ttl_seconds: TokenTTLDep,
) -> TokenOut:
    token = await service.login(payload)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        expires_in=jwt_ttl_seconds,
    )


@router.get(
    "/me",
    response_model=UserOut,
    status_code=status.HTTP_200_OK,
)
async def get_me(
    current_user: CurrentUser,
    service: AuthServiceDep,
) -> UserOut:
    user = await service.get_user(current_user.id)
    return UserOut.model_validate(user)
