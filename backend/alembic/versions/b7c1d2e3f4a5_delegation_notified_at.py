"""delegation.notified_at — отметка, что напоминание «пора проверить» отправлено

Revision ID: b7c1d2e3f4a5
Revises: a5d27fe57e15
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c1d2e3f4a5'
down_revision = 'a5d27fe57e15'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('delegations', sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('delegations', 'notified_at')
