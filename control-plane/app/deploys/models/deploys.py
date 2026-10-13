"""ORM model of the deploys table (only repositories/sql.py uses it)."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.apps.models.apps import AppModel
from app.core.db import Base
from app.core.models import TimestampMixin


# TODO index for the history cursor:
#  1. Import Index from sqlalchemy; inside the class: __table_args__ = (Index("ix_deploys_app_created",
#     "app_name", "created_at", "id"),) — column order matters: filter by app_name, then walk created_at, id.
#  2. DATABASE_URL=postgresql+asyncpg://bult:bult@localhost:5432/bult uv run alembic revision --autogenerate -m "deploys history index"
#  3. Read the new file in migrations/versions (create_index / drop_index only), then `alembic upgrade head`.
#  4. The old single-column ix_deploys_app_name becomes redundant (the new index starts with app_name) —
#     optional: drop index=True on app_name and let autogenerate drop it in the same migration.
class DeployModel(TimestampMixin, Base):
    __tablename__ = "deploys"
    id: Mapped[str] = mapped_column(String(), primary_key=True)  # the agent's deploy_id
    app_name: Mapped[str] = mapped_column(
        String(length=63), ForeignKey(AppModel.name, ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(), server_default="building")
    commit_sha: Mapped[str] = mapped_column(String(), server_default="")
    image: Mapped[str] = mapped_column(String(), server_default="")
    node: Mapped[str] = mapped_column(String(), server_default="")
    host_port: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str] = mapped_column(String(), server_default="")
