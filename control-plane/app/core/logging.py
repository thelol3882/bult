# app/core/logging.py
import logging


def setup_logging() -> None:
    """Our loggers (app.*) at INFO with a real format; uvicorn keeps its own config."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("app").setLevel(logging.INFO)
