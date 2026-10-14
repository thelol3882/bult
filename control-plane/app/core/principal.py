"""Who is making the request, as services see it (no FastAPI, no auth internals)."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    id: UUID
    email: str
