"""Logging setup: our loggers at INFO, every record carries the request's trace id."""

import logging

from app.core.middleware import trace_id_var


class TraceIdFilter(logging.Filter):
    """Adds `trace_id` to every record (background tasks inherit it from the request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get() or "-"
        return True


def setup_logging() -> None:
    """app.* at INFO with a trace-id format; uvicorn keeps its own config."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s [%(trace_id)s]: %(message)s",
    )
    # On handlers: a logger filter skips records from child loggers.
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, TraceIdFilter) for f in handler.filters):
            handler.addFilter(TraceIdFilter())
    logging.getLogger("app").setLevel(logging.INFO)
