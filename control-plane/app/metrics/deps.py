"""Depends wiring of the metrics domain."""

from typing import Annotated

from fastapi import Depends, Request

from app.metrics.services.metrics import MetricsService


def get_metrics_service(request: Request) -> MetricsService:
    """One service per process, built in the lifespan."""
    return request.app.state.metrics


MetricsServiceDep = Annotated[MetricsService, Depends(get_metrics_service)]
