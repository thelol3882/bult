"""ORM model of the users table (only repositories/sql.py uses it)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin, UUIDv7PkMixin


class UserModel(UUIDv7PkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(length=320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(), nullable=False)
