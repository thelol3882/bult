"""Pydantic schemas of the metrics resource."""

from datetime import datetime

from pydantic import BaseModel

from app.metrics.services.metrics import AppMetrics, Period


class SeriesOut(BaseModel):
    replica_id: str
    index: int
    node: str
    points: list[tuple[datetime, float, int]]  # [ts, cpu_limit_pct, mem_bytes]
    live: bool = True  # False for a replica that is gone; its history is still returned


class SummaryOut(BaseModel):
    cpu_cores: float
    mem_bytes: int
    mem_limit_bytes: int
    ready_replicas: int
    desired_replicas: int


class MetricsOut(BaseModel):
    period: Period
    bucket_seconds: int
    series: list[SeriesOut]
    summary: SummaryOut

    @classmethod
    def from_metrics(cls, m: AppMetrics) -> "MetricsOut":
        return cls(
            period=m.period,
            bucket_seconds=m.bucket_seconds,
            series=[
                SeriesOut(
                    replica_id=s.replica_id,
                    index=s.index,
                    node=s.node,
                    points=[(p.ts, p.cpu_limit_pct, p.mem_bytes) for p in s.points],
                    live=s.live,
                )
                for s in m.series
            ],
            summary=SummaryOut(
                cpu_cores=m.summary.cpu_cores,
                mem_bytes=m.summary.mem_bytes,
                mem_limit_bytes=m.summary.mem_limit_bytes,
                ready_replicas=m.summary.ready_replicas,
                desired_replicas=m.summary.desired_replicas,
            ),
        )
