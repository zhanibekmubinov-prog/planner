"""v0.7: чеклист внутри задачи (tasks.checklist JSON).

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('checklist', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('tasks', 'checklist')
