"""nodes and replicas

Revision ID: 78286efa9556
Revises: 2246edc11d97
Create Date: 2026-10-18 18:01:55.255221

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "78286efa9556"
down_revision: Union[str, Sequence[str], None] = "2246edc11d97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    deploys.node / host_port move into replicas: every deploy that ran gets its replica 0.
    """
    op.create_table(
        "nodes",
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("version", sa.String(), server_default="", nullable=False),
        sa.Column("cpus", sa.Integer(), server_default="0", nullable=False),
        sa.Column("memory_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_nodes")),
    )
    op.create_table(
        "replicas",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("deploy_id", sa.String(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(), nullable=False),
        sa.Column("host_port", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="running", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["deploy_id"],
            ["deploys.id"],
            name=op.f("fk_replicas_deploy_id_deploys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_replicas")),
        sa.UniqueConstraint("deploy_id", "index", name=op.f("uq_replicas_deploy_id")),
    )
    op.add_column(
        "deploys",
        sa.Column(
            "desired_replicas", sa.Integer(), server_default="1", nullable=False
        ),
    )
    op.add_column(
        "deploys",
        sa.Column("ran", sa.Boolean(), server_default="false", nullable=False),
    )

    # Only a running deploy still has its container; the others keep the row as history.
    op.execute(
        """
        INSERT INTO replicas (id, deploy_id, index, node, host_port, status)
        SELECT id || '-r0', id, 0, node, host_port,
               CASE WHEN status = 'running' THEN 'running' ELSE 'removed' END
        FROM deploys
        WHERE node <> ''
        """
    )
    op.execute("UPDATE deploys SET ran = true WHERE node <> ''")

    op.drop_column("deploys", "node")
    op.drop_column("deploys", "host_port")

    op.create_check_constraint(
        "replicas_range", "apps", "replicas BETWEEN 0 AND 5"
    )


def downgrade() -> None:
    """Downgrade schema (replica 0 of each deploy goes back into deploys)."""
    op.drop_constraint(op.f("ck_apps_replicas_range"), "apps", type_="check")

    op.add_column(
        "deploys",
        sa.Column(
            "host_port",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.add_column(
        "deploys",
        sa.Column(
            "node",
            sa.VARCHAR(),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE deploys SET node = r.node, host_port = r.host_port
        FROM replicas r
        WHERE r.deploy_id = deploys.id AND r.index = 0
        """
    )
    op.drop_column("deploys", "ran")
    op.drop_column("deploys", "desired_replicas")
    op.drop_table("replicas")
    op.drop_table("nodes")
