"""ORM model of the replicas table (only repositories/sql.py uses it)."""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
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
    status: Mapped[str] = mapped_column(String(), server_default="running")

    __table_args__ = (UniqueConstraint("deploy_id", "index"),)
