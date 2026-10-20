"""ORM model of the replica_metrics table (only repositories/sql.py uses it)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Identity, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ReplicaMetricModel(Base):
    __tablename__ = "replica_metrics"
    id: Mapped[int] = mapped_column(BigInteger(), Identity(), primary_key=True)
    replica_id: Mapped[str] = mapped_column(String())  # "<deploy_id>-r<index>"
    app_name: Mapped[str] = mapped_column(String())
    node: Mapped[str] = mapped_column(String())
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cpu_cores: Mapped[float] = mapped_column(Float())
    cpu_limit_pct: Mapped[float] = mapped_column(Float())
    mem_bytes: Mapped[int] = mapped_column(BigInteger())
    mem_limit_bytes: Mapped[int] = mapped_column(BigInteger())

    __table_args__ = (
        Index("ix_replica_metrics_app_name_ts", "app_name", "ts"),
        Index("ix_replica_metrics_replica_id_ts", "replica_id", "ts"),
    )
