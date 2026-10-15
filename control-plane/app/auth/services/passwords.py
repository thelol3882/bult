"""Password hashing (argon2id via pwdlib)."""

import asyncio

from pwdlib import PasswordHash


class PasswordHasher:
    """Hashing is slow CPU work; argon2 releases the GIL, so a thread keeps the event loop free."""

    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()
        self._dummy_hash = self._hasher.hash("dummy_constant_password_value")

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password: str, password_hash: str) -> tuple[bool, str | None]:
        """(ok, new_hash) — new_hash is set when the stored hash uses old parameters."""
        return await asyncio.to_thread(self._hasher.verify_and_update, password, password_hash)

    async def burn(self, password: str) -> None:
        """Spend the same time as a real check when there is no user."""
        await asyncio.to_thread(self._hasher.verify_and_update, password, self._dummy_hash)
