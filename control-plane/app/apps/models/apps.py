"""ORM model of the apps table (only repositories/sql.py uses it)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin, UUIDv7PkMixin


class AppModel(UUIDv7PkMixin, TimestampMixin, Base):
    __tablename__ = "apps"
    name: Mapped[str] = mapped_column(String(length=63), unique=True)
    preset: Mapped[str] = mapped_column(String(), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(), nullable=False)
    branch: Mapped[str] = mapped_column(String(), nullable=False)
    subdir: Mapped[str] = mapped_column(String(), server_default="")
