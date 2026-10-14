"""Auth API tests: real tokens end to end, in-memory storage."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.auth.repositories.users import User
from app.auth.uow import InMemoryAuthUoW
from tests.fakes import PASSWORD, TEST_JWT_SECRET

EMAIL = "carol@example.com"


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def forged_token(
    secret: str | None = TEST_JWT_SECRET,
    algorithm: str = "HS256",
    expires_in: timedelta = timedelta(hours=1),
) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(uuid4()), "iat": now, "exp": now + expires_in}
    return jwt.encode(payload, secret, algorithm=algorithm)  # pyright: ignore[reportArgumentType]


def test_register_login_me(anon_client: TestClient):
    registered = register(anon_client)
    assert registered.status_code == 201
    assert registered.json()["email"] == EMAIL
    assert "password" not in registered.text

    token = login(anon_client).json()["access_token"]
    me = anon_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["id"] == registered.json()["id"]


def test_register_duplicate_email_is_409(anon_client: TestClient):
    register(anon_client)

    resp = register(anon_client)

    assert resp.status_code == 409
    assert resp.json()["code"] == "email_taken"
    assert resp.json()["field"] == "email"


def test_register_same_email_in_another_case_is_409(anon_client: TestClient):
    register(anon_client, "dave@example.com")

    resp = register(anon_client, "Dave@Example.com")

    assert resp.status_code == 409
    assert resp.json()["code"] == "email_taken"


def test_register_short_password_is_422(anon_client: TestClient):
    resp = register(anon_client, password="short")

    assert resp.status_code == 422
    assert "password" in resp.json()["fields"]


def test_wrong_password_and_unknown_email_look_the_same(anon_client: TestClient):
    register(anon_client)

    wrong_password = login(anon_client, password="not the password")
    unknown_email = login(anon_client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    bodies = [r.json() for r in (wrong_password, unknown_email)]
    for body in bodies:
        del body["trace_id"]
    assert bodies[0] == bodies[1]
    assert bodies[0]["code"] == "invalid_credentials"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer garbage"},
        {"Authorization": f"Bearer {forged_token(expires_in=timedelta(hours=-1))}"},
        {"Authorization": f"Bearer {forged_token(secret='another-key-' + 'y' * 32)}"},
        {"Authorization": f"Bearer {forged_token(secret=None, algorithm='none')}"},
    ],
    ids=["no-token", "garbage", "expired", "other-key", "alg-none"],
)
def test_bad_token_is_not_authenticated(anon_client: TestClient, headers: dict):
    resp = anon_client.get("/auth/me", headers=headers)

    assert resp.status_code == 401
    assert resp.json()["code"] == "not_authenticated"


def test_token_of_unknown_user_is_not_authenticated(anon_client: TestClient):
    resp = anon_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {forged_token()}"}
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "not_authenticated"


def test_login_rehashes_a_weaker_hash(
    anon_client: TestClient, auth_uow: InMemoryAuthUoW
):
    weak = PasswordHash(
        (Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),)
    ).hash(PASSWORD)
    asyncio.run(auth_uow.users.add(User(email=EMAIL, password_hash=weak)))

    assert login(anon_client).status_code == 200

    new_hash = asyncio.run(auth_uow.users.get_by_email(EMAIL))
    assert new_hash is not None
    assert new_hash.password_hash != weak
    assert "m=64,t=2" in new_hash.password_hash
    assert login(anon_client).status_code == 200

