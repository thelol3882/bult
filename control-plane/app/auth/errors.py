"""Errors of the auth domain."""

from app.core.error_codes import ErrorCode
from app.core.errors import ConflictError, UnauthorizedError


class EmailTakenError(ConflictError):
    code = ErrorCode.EMAIL_TAKEN

    def __init__(self, email: str) -> None:
        super().__init__(f"Email '{email}' is already taken.", field="email")


class InvalidCredentialsError(UnauthorizedError):
    code = ErrorCode.INVALID_CREDENTIALS

    def __init__(self) -> None:
        super().__init__("No such email or wrong password")


class NotAuthenticatedError(UnauthorizedError):
    code = ErrorCode.NOT_AUTHENTICATED

    def __init__(self) -> None:
        super().__init__("Not authenticated")
