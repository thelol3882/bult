"""Metric sample storage behind a Protocol."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

# date_bin() aligns buckets to this instant; the in-memory fake must use the same one.
BUCKET_ORIGIN = datetime(2000, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ReplicaSample:
    """One reading of a replica, as the node reported it."""

    replica_id: str
    app_name: str
    node: str
    ts: datetime
    cpu_cores: float
    cpu_limit_pct: float
    mem_bytes: int
    mem_limit_bytes: int


@dataclass(frozen=True)
class SeriesPoint:
    """The average of a replica's samples in one time bucket (`ts` is the bucket start)."""

    replica_id: str
    node: str
    ts: datetime
    cpu_limit_pct: float
    mem_bytes: int


class MetricsRepository(Protocol):
    """Storage only; what to keep and how to present it lives in MetricsService."""

    async def add_many(self, samples: Iterable[ReplicaSample]) -> None: ...

    async def delete_older_than(self, cutoff: datetime, limit: int) -> int:
        """Delete up to `limit` samples with ts < cutoff; returns how many went."""
        ...

    async def delete_for_app(self, app_name: str) -> None: ...

    async def series(
        self, app_name: str, since: datetime, bucket_seconds: int
    ) -> list[SeriesPoint]:
        """Per replica, the averages of ts >= since in buckets of `bucket_seconds`,
        ordered by (replica_id, ts)."""
        ...

    async def latest(self, app_name: str, since: datetime) -> list[ReplicaSample]:
        """The newest sample of each replica of the app with ts >= since."""
        ...


class InMemoryMetricsRepository:
    """List of samples; also the test fake. Buckets like date_bin(), from BUCKET_ORIGIN."""

    def __init__(self) -> None:
        self.samples: list[ReplicaSample] = []

    async def add_many(self, samples: Iterable[ReplicaSample]) -> None:
        self.samples.extend(samples)

    async def delete_older_than(self, cutoff: datetime, limit: int) -> int:
        old = [s for s in self.samples if s.ts < cutoff][:limit]
        gone = {id(s) for s in old}
        self.samples = [s for s in self.samples if id(s) not in gone]
        return len(old)

    async def delete_for_app(self, app_name: str) -> None:
        self.samples = [s for s in self.samples if s.app_name != app_name]

    async def series(
        self, app_name: str, since: datetime, bucket_seconds: int
    ) -> list[SeriesPoint]:
        buckets: dict[tuple[str, str, datetime], list[ReplicaSample]] = {}
        for s in self.samples:
            if s.app_name != app_name or s.ts < since:
                continue
            n = int((s.ts - BUCKET_ORIGIN).total_seconds() // bucket_seconds)
            start = BUCKET_ORIGIN + timedelta(seconds=n * bucket_seconds)
            buckets.setdefault((s.replica_id, s.node, start), []).append(s)
        points = [
            SeriesPoint(
                replica_id=replica_id,
                node=node,
                ts=start,
                cpu_limit_pct=sum(s.cpu_limit_pct for s in group) / len(group),
                mem_bytes=round(sum(s.mem_bytes for s in group) / len(group)),
            )
            for (replica_id, node, start), group in buckets.items()
        ]
        return sorted(points, key=lambda p: (p.replica_id, p.ts))

    async def latest(self, app_name: str, since: datetime) -> list[ReplicaSample]:
        newest: dict[str, ReplicaSample] = {}
        for s in self.samples:
            if s.app_name != app_name or s.ts < since:
                continue
            if s.replica_id not in newest or s.ts >= newest[s.replica_id].ts:
                newest[s.replica_id] = s
        return sorted(newest.values(), key=lambda s: s.replica_id)
