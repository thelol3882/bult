"""Password hashing (argon2id via pwdlib)."""

from pwdlib import PasswordHash


class PasswordHasher:
    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()
        self._dummy_hash = self._hasher.hash("dummy_constant_password_value")

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> tuple[bool, str | None]:
        """(ok, new_hash) — new_hash is set when the stored hash uses old parameters."""
        return self._hasher.verify_and_update(password, password_hash)

    def burn(self, password: str) -> None:
        """Spend the same time as a real check when there is no user."""
        self._hasher.verify_and_update(password, self._dummy_hash)
