"""ORM model of the apps table (only repositories/sql.py uses it)."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
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
    health_path: Mapped[str] = mapped_column(String(), server_default="")
    replicas: Mapped[int] = mapped_column(server_default="1")  # desired: 0 = stopped, max 5
    # Write-only for the API: only the keys are ever returned.
    env: Mapped[dict[str, str]] = mapped_column(
        JSONB(), server_default=text("'{}'::jsonb")
    )
    # [{"path": "/api", "app": "shop-api"}]: paths of this app's domain served by other apps.
    routes: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB(), server_default=text("'[]'::jsonb")
    )
    # Table name, not UserModel: the apps domain must not import app.auth.
    # RESTRICT: a cascade would orphan the replicas running on the nodes.
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )

    __table_args__ = (
        # Keep in sync with core.config.MAX_REPLICAS.
        CheckConstraint("replicas BETWEEN 0 AND 5", name="replicas_range"),
    )
