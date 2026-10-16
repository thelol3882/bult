"""ORM model of the deploys table (only repositories/sql.py uses it)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.apps.models.apps import AppModel
from app.core.db import Base
from app.core.models import TimestampMixin
from app.deploys.repositories.deploys import ACTIVE_STATUSES


class DeployModel(TimestampMixin, Base):
    __tablename__ = "deploys"
    id: Mapped[str] = mapped_column(String(), primary_key=True)  # the agent's deploy_id
    app_name: Mapped[str] = mapped_column(
        String(length=63), ForeignKey(AppModel.name, ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(), server_default="queued")
    commit_sha: Mapped[str] = mapped_column(String(), server_default="")
    image: Mapped[str] = mapped_column(String(), server_default="")
    node: Mapped[str] = mapped_column(String(), server_default="")
    host_port: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str] = mapped_column(String(), server_default="")
    lease_owner: Mapped[str] = mapped_column(String(), server_default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer(), server_default="0")

    __table_args__ = (
        Index("ix_deploys_app_created", "app_name", "created_at", "id"),
        Index(
            "uq_deploys_app_active",
            "app_name",
            unique=True,
            postgresql_where=status.in_(ACTIVE_STATUSES),
        ),
    )
