"""reminders.recipient — кому уходит напоминание: владельцу, исполнителям или обоим.

Revision ID: e0f4a5b6c7d8
Revises: d9e3f4a5b6c7
"""
from alembic import op
import sqlalchemy as sa


revision = 'e0f4a5b6c7d8'
down_revision = 'd9e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('reminders', sa.Column('recipient', sa.String(length=16), server_default='owner', nullable=False))


def downgrade() -> None:
    op.drop_column('reminders', 'recipient')
