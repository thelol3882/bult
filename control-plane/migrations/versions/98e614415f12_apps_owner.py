"""apps owner

Revision ID: 98e614415f12
Revises: 4ad03ec3dce7
Create Date: 2026-10-14 20:09:32.046566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98e614415f12'
down_revision: Union[str, Sequence[str], None] = '4ad03ec3dce7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Dev reset: an app cannot exist without an owner. A real deployment would
    # backfill owner_id from a known user instead of deleting.
    op.execute("DELETE FROM apps")  # cascades to deploys
    op.add_column('apps', sa.Column('owner_id', sa.Uuid(), nullable=False))
    op.create_index(op.f('ix_apps_owner_id'), 'apps', ['owner_id'], unique=False)
    op.create_foreign_key(op.f('fk_apps_owner_id_users'), 'apps', 'users', ['owner_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_apps_owner_id_users'), 'apps', type_='foreignkey')
    op.drop_index(op.f('ix_apps_owner_id'), table_name='apps')
    op.drop_column('apps', 'owner_id')
