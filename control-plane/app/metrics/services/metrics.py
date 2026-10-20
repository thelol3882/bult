"""Metrics rules: store what the nodes report, keep a day of it, and shape it for charts."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.apps.services.facade import AppsFacade
from app.core.principal import Principal
from app.deploys.services.facade import DeploysFacade
from app.metrics.repositories.metrics import ReplicaSample
from app.metrics.uow import MetricsUoW

Period = Literal["15m", "1h", "24h"]
PERIOD_SECONDS: dict[Period, int] = {"15m": 900, "1h": 3600, "24h": 86400}

HEARTBEAT_SECONDS = 5  # a bucket narrower than the reporting interval would only hold one sample
MAX_POINTS = 300  # per series
# A replica counts towards the "current" totals only if it reported this recently
# (three missed heartbeats, like a node's TTL).
LIVE_SECONDS = 15
PURGE_BATCH = 5000


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class UsageSample:
    """What a node reports about one replica (no app or time yet)."""

    replica_id: str
    cpu_cores: float
    cpu_limit_pct: float
    mem_bytes: int
    mem_limit_bytes: int


@dataclass(frozen=True)
class Point:
    ts: datetime
    cpu_limit_pct: float
    mem_bytes: int


@dataclass(frozen=True)
class Series:
    replica_id: str
    index: int
    node: str
    points: tuple[Point, ...]
    live: bool  # the replica is running now; False once it was removed


@dataclass(frozen=True)
class Summary:
    cpu_cores: float
    mem_bytes: int
    mem_limit_bytes: int
    ready_replicas: int
    desired_replicas: int


@dataclass(frozen=True)
class AppMetrics:
    period: Period
    bucket_seconds: int
    series: tuple[Series, ...]
    summary: Summary


def bucket_seconds(period: Period) -> int:
    """Bucket width that gives at most MAX_POINTS points per series.

    The window start is not aligned to a bucket, so it touches one bucket more than
    period / width; one spare bucket is kept free for that.
    """
    return max(HEARTBEAT_SECONDS, math.ceil(PERIOD_SECONDS[period] / (MAX_POINTS - 1)))


def replica_index(replica_id: str) -> int:
    """The index in a "<deploy_id>-r<index>" id; 0 if the id has another shape."""
    _, sep, tail = replica_id.rpartition("-r")
    return int(tail) if sep and tail.isdigit() else 0


class MetricsService:
    def __init__(
        self,
        uow_factory: Callable[[], MetricsUoW],
        apps: AppsFacade,
        deploys: DeploysFacade,
        *,
        retention_hours: float = 24.0,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._apps = apps
        self._deploys = deploys
        self._retention = timedelta(hours=retention_hours)
        self._clock = clock

    async def record(self, node: str, usage: Sequence[UsageSample]) -> int:
        """Store a node's readings; returns how many were kept.

        Replica ids that are not running replicas of a deploy, or run on another node than
        the reporter, are ignored: a node can only speak for its own replicas.
        """
        if not usage:
            return 0
        owners = await self._deploys.replica_owners(u.replica_id for u in usage)
        now = self._clock()
        rows = [
            ReplicaSample(
                replica_id=u.replica_id,
                app_name=owner.app_name,
                node=node,
                ts=now,
                cpu_cores=u.cpu_cores,
                cpu_limit_pct=u.cpu_limit_pct,
                mem_bytes=u.mem_bytes,
                mem_limit_bytes=u.mem_limit_bytes,
            )
            for u in usage
            if (owner := owners.get(u.replica_id)) is not None and owner.node == node
        ]
        if not rows:
            return 0
        async with self._uow_factory() as uow:
            await uow.metrics.add_many(rows)
            await uow.commit()
        return len(rows)

    async def purge(self) -> int:
        """Delete samples older than the retention, in batches; returns how many went."""
        cutoff = self._clock() - self._retention
        total = 0
        while True:
            async with self._uow_factory() as uow:
                deleted = await uow.metrics.delete_older_than(cutoff, PURGE_BATCH)
                await uow.commit()
            total += deleted
            if deleted < PURGE_BATCH:
                return total

    async def forget_app(self, app_name: str) -> None:
        """The app was deleted: a new app with the same name must not inherit its history."""
        async with self._uow_factory() as uow:
            await uow.metrics.delete_for_app(app_name)
            await uow.commit()

    async def query(self, name: str, period: Period, principal: Principal) -> AppMetrics:
        app = await self._apps.get_app(name, principal)
        now = self._clock()
        width = bucket_seconds(period)
        async with self._uow_factory() as uow:
            points = await uow.metrics.series(
                name, now - timedelta(seconds=PERIOD_SECONDS[period]), width
            )
            live = await uow.metrics.latest(name, now - timedelta(seconds=LIVE_SECONDS))

        by_replica: dict[str, list[Point]] = {}
        node_of: dict[str, str] = {}
        for p in points:
            by_replica.setdefault(p.replica_id, []).append(
                Point(p.ts, round(p.cpu_limit_pct, 1), p.mem_bytes)
            )
            node_of[p.replica_id] = p.node  # the newest bucket wins
        running = await self._deploys.replica_owners(by_replica)
        series = tuple(
            sorted(
                (
                    Series(rid, replica_index(rid), node_of[rid], tuple(pts), rid in running)
                    for rid, pts in by_replica.items()
                ),
                key=lambda s: (s.index, s.replica_id),
            )
        )
        summary = Summary(
            cpu_cores=round(sum(s.cpu_cores for s in live), 3),
            mem_bytes=sum(s.mem_bytes for s in live),
            mem_limit_bytes=sum(s.mem_limit_bytes for s in live),
            ready_replicas=await self._deploys.ready_replicas(name),
            desired_replicas=app.replicas,
        )
        return AppMetrics(period, width, series, summary)
