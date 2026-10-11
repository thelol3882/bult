"""Turns exceptions into the error body {detail, code, trace_id, field?, fields?}."""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.core.middleware import TRACE_ID_HEADER, trace_id_var

logger = logging.getLogger(__name__)

_REQUEST_PARTS = {"body", "query", "path"}


def _trace_id(request: Request) -> str:
    return (
        getattr(request.state, "trace_id", "") or trace_id_var.get() or uuid.uuid4().hex
    )


def _respond(request: Request, status: int, body: dict[str, Any]) -> JSONResponse:
    trace_id = _trace_id(request)
    return JSONResponse(
        status_code=status,
        content={**body, "trace_id": trace_id},
        headers={TRACE_ID_HEADER: trace_id},
    )


def _clean(msg: str) -> str:
    # Pydantic prefixes custom validator messages with "Value error, ".
    return msg.removeprefix("Value error, ")


def _field_name(error: Any) -> str:
    """('body', 'a', 0, 'b') -> 'a.0.b'; broken JSON -> 'body'."""
    loc = error["loc"]
    if error["type"] == "json_invalid":
        return "body"
    if loc and loc[0] in _REQUEST_PARTS:
        loc = loc[1:]
    return ".".join(str(part) for part in loc) or "body"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    body: dict[str, Any] = {"detail": exc.detail, "code": str(exc.code)}
    if exc.field is not None:
        body["field"] = exc.field
    return _respond(request, exc.status, body)


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields: dict[str, str] = {}
    for error in exc.errors():
        fields.setdefault(_field_name(error), _clean(error["msg"]))
    return _respond(
        request,
        422,
        {
            "detail": "Invalid request",
            "code": str(ErrorCode.VALIDATION_ERROR),
            "fields": fields,
        },
    )


_HTTP_CODES = {
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
}


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Unknown routes, wrong methods: same body as our own errors."""
    response = _respond(
        request,
        exc.status_code,
        {
            "detail": str(exc.detail),
            "code": str(_HTTP_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)),
        },
    )
    if exc.headers:  # e.g. Allow on 405
        response.headers.update(exc.headers)
    return response


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled error on %s %s", request.method, request.url.path, exc_info=exc
    )
    return _respond(
        request,
        500,
        {"detail": "Internal server error", "code": str(ErrorCode.INTERNAL_ERROR)},
    )


def register(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(Exception, unhandled_error_handler)
