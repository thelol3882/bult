"""ORM model of the replicas table (only repositories/sql.py uses it)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin


class ReplicaModel(TimestampMixin, Base):
    __tablename__ = "replicas"
    id: Mapped[str] = mapped_column(String(), primary_key=True)  # "<deploy_id>-r<index>"
    deploy_id: Mapped[str] = mapped_column(
        String(), ForeignKey("deploys.id", ondelete="CASCADE")
    )
    index: Mapped[int] = mapped_column(Integer())
    node: Mapped[str] = mapped_column(String())
    host_port: Mapped[int] = mapped_column(Integer())
    status: Mapped[str] = mapped_column(String(), server_default="running")  # running | removed
    # What the platform observes of the container (see ReplicaState).
    state: Mapped[str] = mapped_column(String(), server_default="running")
    healthy: Mapped[bool] = mapped_column(Boolean(), server_default="true")
    exit_code: Mapped[int | None] = mapped_column(Integer())
    reason: Mapped[str] = mapped_column(String(), server_default="")
    log_tail: Mapped[str] = mapped_column(String(), server_default="")
    tail_pending: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    unhealthy_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[list[datetime]] = mapped_column(
        ARRAY(DateTime(timezone=True)), server_default=text("'{}'::timestamptz[]")
    )
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("deploy_id", "index"),)
