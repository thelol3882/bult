"""ORM model of the deploys table (only repositories/sql.py uses it)."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.apps.models.apps import AppModel
from app.core.db import Base
from app.core.models import TimestampMixin


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
