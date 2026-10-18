"""ORM model of the nodes table (only repositories/sql.py uses it)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin


class NodeModel(TimestampMixin, Base):
    __tablename__ = "nodes"
    name: Mapped[str] = mapped_column(String(length=63), primary_key=True)
    address: Mapped[str] = mapped_column(String())  # host:port of the agent's gRPC server
    role: Mapped[str] = mapped_column(String())  # builder | runner | both
    version: Mapped[str] = mapped_column(String(), server_default="")
    cpus: Mapped[int] = mapped_column(Integer(), server_default="0")
    memory_bytes: Mapped[int] = mapped_column(BigInteger(), server_default="0")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
