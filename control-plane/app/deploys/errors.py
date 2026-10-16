"""Errors the deploys repositories raise (services keep their own in services/deploys.py)."""

from app.core.error_codes import ErrorCode
from app.core.errors import ConflictError


class DeployInProgressError(ConflictError):
    code = ErrorCode.DEPLOY_IN_PROGRESS

    def __init__(self, name: str) -> None:
        super().__init__(
            f"App '{name}' already has a deploy in progress. Wait for it to finish."
        )
