"""Access tokens (JWT, HS256 via PyJWT)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    """Any reason a token cannot be trusted."""


class TokenIssuer:
    def __init__(self, secret: str, ttl_seconds: int) -> None:
        self._secret = secret
        self._ttl = timedelta(seconds=ttl_seconds)

    def issue(self, user_id: UUID) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "iat": now,
            "exp": now + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def user_id(self, token: str) -> UUID:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                options={"require": ["sub", "iat", "exp"]},
            )
            sub = payload.get("sub")
            if not isinstance(sub, str):
                raise InvalidTokenError("Missing or non-string 'sub' claim")
            return UUID(sub)
        except (jwt.PyJWTError, ValueError):
            raise InvalidTokenError("Invalid or expired token") from None
