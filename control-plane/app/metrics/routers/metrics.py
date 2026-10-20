"""CPU and memory of an app's replicas."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.deps import CurrentUser
from app.metrics.deps import MetricsServiceDep
from app.metrics.schemas.metrics import MetricsOut
from app.metrics.services.metrics import Period

router = APIRouter(prefix="/apps/{name}", tags=["metrics"])


@router.get("/metrics", response_model=MetricsOut)
async def get_metrics(
    name: str,
    service: MetricsServiceDep,
    user: CurrentUser,
    period: Annotated[Period, Query()] = "15m",
) -> MetricsOut:
    return MetricsOut.from_metrics(await service.query(name, period, user))
