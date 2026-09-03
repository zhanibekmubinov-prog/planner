"""mindmaps — майндмапы (дерево узлов в JSON), привязка к направлению/задаче

Revision ID: c8d2e3f4a5b6
Revises: b7c1d2e3f4a5
"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d2e3f4a5b6'
down_revision = 'b7c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('mindmaps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('direction_id', sa.Integer(), nullable=True),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('mindmaps')
