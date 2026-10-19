from app.core.error_codes import ErrorCode
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)


class AppNameTakenError(ConflictError):
    """An app with this name already exists."""

    code = ErrorCode.APP_NAME_TAKEN

    def __init__(self, name: str) -> None:
        super().__init__(f"App with name '{name}' already exists.", field="name")


class AppNotFoundError(NotFoundError):
    """No app with this name."""

    code = ErrorCode.APP_NOT_FOUND

    def __init__(self, name: str) -> None:
        super().__init__(f"App '{name}' not found.")


class AppForbiddenError(ForbiddenError):
    """The app belongs to another user."""

    code = ErrorCode.FORBIDDEN

    def __init__(self, name: str) -> None:
        super().__init__(f"You do not have access to app '{name}'.")


class RouteToSelfError(UnprocessableError):
    """A path route that points at the app itself."""

    code = ErrorCode.ROUTE_TO_SELF

    def __init__(self, name: str) -> None:
        super().__init__(f"App '{name}' cannot route a path to itself.", field="routes")
