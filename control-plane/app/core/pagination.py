"""Pagination: page numbers for small lists, an opaque cursor for history."""

import base64
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from app.core.error_codes import ErrorCode
from app.core.errors import AppError


class PageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](BaseModel):
    count: int
    next: int | None
    previous: int | None
    results: list[T]

    @classmethod
    def build(cls, results: list[T], count: int, params: PageParams) -> Self:
        total_pages = (
            (count + params.page_size - 1) // params.page_size if count > 0 else 0
        )

        if total_pages > 0 and params.page > total_pages:
            previous = total_pages
        elif 1 < params.page <= total_pages:
            previous = params.page - 1
        else:
            previous = None

        has_next = params.page < total_pages
        next_page = params.page + 1 if has_next else None

        return cls(
            count=count,
            next=next_page,
            previous=previous,
            results=results,
        )


class InvalidCursorError(AppError):
    status = 422
    code = ErrorCode.INVALID_CURSOR

    def __init__(self) -> None:
        super().__init__("Invalid pagination cursor.", field="cursor")


def encode_cursor(created_at: datetime, item_id: str) -> str:
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        ).decode()
        created_at_str, item_id = raw.split("|", 1)
        if not item_id:
            raise ValueError("empty id")
        return datetime.fromisoformat(created_at_str), item_id
    except Exception:
        raise InvalidCursorError() from None


class CursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class CursorPage[T](BaseModel):
    results: list[T]
    next_cursor: str | None
