"""Errors of the nodes domain."""

from app.core.error_codes import ErrorCode
from app.core.errors import UnauthorizedError


class InvalidNodeTokenError(UnauthorizedError):
    """Missing token, unknown node, or a token that belongs to another node (one message for all)."""

    code = ErrorCode.INVALID_NODE_TOKEN

    def __init__(self) -> None:
        super().__init__("Invalid node token")
