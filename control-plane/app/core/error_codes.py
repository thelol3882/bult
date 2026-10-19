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
    ROUTE_TO_SELF = "route_to_self"

    # deploys
    DEPLOY_NOT_FOUND = "deploy_not_found"
    BUILDER_UNAVAILABLE = "builder_unavailable"
    DEPLOY_IN_PROGRESS = "deploy_in_progress"
    NOTHING_TO_START = "nothing_to_start"
    DEPLOY_NOT_RESTORABLE = "deploy_not_restorable"
    APP_ALREADY_RUNNING = "app_already_running"
    NODE_UNAVAILABLE = "node_unavailable"
    DEPLOY_NOT_CANCELLABLE = "deploy_not_cancellable"

    REPLICA_NOT_FOUND = "replica_not_found"
    NO_NODE_AVAILABLE = "no_node_available"

    # nodes
    INVALID_NODE_TOKEN = "invalid_node_token"

    # pagination
    INVALID_CURSOR = "invalid_cursor"

    # auth
    NOT_AUTHENTICATED = "not_authenticated"
    FORBIDDEN = "forbidden"
    INVALID_CREDENTIALS = "invalid_credentials"
    EMAIL_TAKEN = "email_taken"
