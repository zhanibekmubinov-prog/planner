"""v1.6: ручной порядок проектов и задач (перетаскивание) — sort_order.

Revision ID: f2b6c7d8e9a0
Revises: e6f7a8b9c0d1
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2b6c7d8e9a0'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0 у всех существующих строк = прежний порядок (по id у проектов, по приоритету у задач)
    for table in ('projects', 'tasks'):
        op.add_column(table, sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    for table in ('tasks', 'projects'):
        op.drop_column(table, 'sort_order')
