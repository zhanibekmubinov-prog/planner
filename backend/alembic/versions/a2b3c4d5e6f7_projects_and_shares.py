"""v0.6: проекты внутри направлений (projects, tasks.project_id) и совместный доступ (shares).

Revision ID: a2b3c4d5e6f7
Revises: f1a5b6c7d8e9
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a2b3c4d5e6f7'
down_revision = 'f1a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Статус проекта использует тот же тип, что и статус направления (active / paused / archived)
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('direction_id', sa.Integer(), sa.ForeignKey('directions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('color', sa.String(length=16), nullable=True),
        sa.Column('status', postgresql.ENUM('active', 'paused', 'archived', name='directionstatus', create_type=False), nullable=False, server_default='active'),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_projects_direction_id', 'projects', ['direction_id'])
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'])

    op.add_column('tasks', sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])

    op.create_table(
        'shares',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('entity_type', sa.String(length=16), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('permission', sa.String(length=8), nullable=False, server_default='view'),
        sa.Column('granted_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('entity_type', 'entity_id', 'user_id', name='uq_share_entity_user'),
    )
    op.create_index('ix_shares_entity_type', 'shares', ['entity_type'])
    op.create_index('ix_shares_entity_id', 'shares', ['entity_id'])
    op.create_index('ix_shares_user_id', 'shares', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_shares_user_id', table_name='shares')
    op.drop_index('ix_shares_entity_id', table_name='shares')
    op.drop_index('ix_shares_entity_type', table_name='shares')
    op.drop_table('shares')
    op.drop_index('ix_tasks_project_id', table_name='tasks')
    op.drop_column('tasks', 'project_id')
    op.drop_index('ix_projects_owner_id', table_name='projects')
    op.drop_index('ix_projects_direction_id', table_name='projects')
    op.drop_table('projects')
