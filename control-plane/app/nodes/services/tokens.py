"""Node tokens: one secret per node name, compared in constant time."""

import hmac

from pydantic import SecretStr

# Compared against when the name is unknown, so "no such node" costs the same as "wrong token".
_DUMMY = "x" * 64


class NodeTokens:
    def __init__(self, tokens: dict[str, SecretStr]) -> None:
        self._tokens = {name: t.get_secret_value() for name, t in tokens.items()}

    def verify(self, name: str, presented: str | None) -> bool:
        """True if `presented` is the token bound to exactly this node name."""
        expected = self._tokens.get(name)
        candidate = (presented or "").encode()
        known = expected is not None
        ok = hmac.compare_digest(candidate, (expected if known else _DUMMY).encode())
        return ok and known and presented is not None
