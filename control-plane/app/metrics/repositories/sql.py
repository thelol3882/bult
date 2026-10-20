"""MetricsRepository on PostgreSQL."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics.models.metrics import ReplicaMetricModel as M
from app.metrics.repositories.metrics import (
    BUCKET_ORIGIN,
    ReplicaSample,
    SeriesPoint,
)


class SqlMetricsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, samples: Iterable[ReplicaSample]) -> None:
        rows = [
            {
                "replica_id": s.replica_id,
                "app_name": s.app_name,
                "node": s.node,
                "ts": s.ts,
                "cpu_cores": s.cpu_cores,
                "cpu_limit_pct": s.cpu_limit_pct,
                "mem_bytes": s.mem_bytes,
                "mem_limit_bytes": s.mem_limit_bytes,
            }
            for s in samples
        ]
        if rows:
            await self._session.execute(insert(M), rows)

    async def delete_older_than(self, cutoff: datetime, limit: int) -> int:
        oldest = select(M.id).where(M.ts < cutoff).limit(limit)
        result = await self._session.execute(delete(M).where(M.id.in_(oldest)))
        return result.rowcount  # pyright: ignore[reportAttributeAccessIssue]

    async def delete_for_app(self, app_name: str) -> None:
        await self._session.execute(delete(M).where(M.app_name == app_name))

    async def series(
        self, app_name: str, since: datetime, bucket_seconds: int
    ) -> list[SeriesPoint]:
        # date_bin snaps ts to the start of its bucket; the average is per bucket and replica.
        bucket = func.date_bin(
            timedelta(seconds=bucket_seconds), M.ts, BUCKET_ORIGIN
        ).label("bucket")
        rows = await self._session.execute(
            select(
                M.replica_id,
                M.node,
                bucket,
                func.avg(M.cpu_limit_pct),
                func.avg(M.mem_bytes),
            )
            .where(M.app_name == app_name, M.ts >= since)
            .group_by(M.replica_id, M.node, bucket)
            .order_by(M.replica_id, bucket)
        )
        return [
            SeriesPoint(replica_id, node, ts, float(cpu), round(float(mem)))
            for replica_id, node, ts, cpu, mem in rows.all()
        ]

    async def latest(self, app_name: str, since: datetime) -> list[ReplicaSample]:
        rows = await self._session.scalars(
            select(M)
            .where(M.app_name == app_name, M.ts >= since)
            .ext(distinct_on(M.replica_id))
            .order_by(M.replica_id, M.ts.desc())
        )
        return [
            ReplicaSample(
                replica_id=r.replica_id,
                app_name=r.app_name,
                node=r.node,
                ts=r.ts,
                cpu_cores=r.cpu_cores,
                cpu_limit_pct=r.cpu_limit_pct,
                mem_bytes=r.mem_bytes,
                mem_limit_bytes=r.mem_limit_bytes,
            )
            for r in rows.all()
        ]
