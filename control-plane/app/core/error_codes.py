"""Machine-readable error codes for the `code` field; clients branch on these, not on `detail`."""

from enum import StrEnum


class ErrorCode(StrEnum):
    # generic: used when a domain has no more specific code
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    HTTP_ERROR = "http_error"  # any other framework-level HTTP error
    CONFLICT = "conflict"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"

    # apps
    APP_NOT_FOUND = "app_not_found"
    APP_NAME_TAKEN = "app_name_taken"

    # deploys
    DEPLOY_NOT_FOUND = "deploy_not_found"
    BUILDER_UNAVAILABLE = "builder_unavailable"

    # pagination
    INVALID_CURSOR = "invalid_cursor"
