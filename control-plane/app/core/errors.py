"""Errors services raise; no FastAPI import so non-HTTP callers can use them (`status` is HTTP-like)."""

from app.core.error_codes import ErrorCode


class AppError(Exception):
    """Base class; `detail` must be safe to show to users."""

    status: int = 500
    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        detail: str,
        *,
        code: ErrorCode | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.field = field  # request field the error is about, if any
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status = 404
    code = ErrorCode.NOT_FOUND


class ConflictError(AppError):
    status = 409
    code = ErrorCode.CONFLICT


class ServiceUnavailableError(AppError):
    status = 503
    code = ErrorCode.SERVICE_UNAVAILABLE


class InternalError(AppError):
    status = 500
    code = ErrorCode.INTERNAL_ERROR


class UnauthorizedError(AppError):
    status = 401
    code = ErrorCode.NOT_AUTHENTICATED


class ForbiddenError(AppError):
    status = 403
    code = ErrorCode.FORBIDDEN
