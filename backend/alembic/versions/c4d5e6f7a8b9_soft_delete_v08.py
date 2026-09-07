"""v0.8: корзина (deleted_at у directions/projects/tasks) и запрет удаления человека с поручениями (RESTRICT).

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('directions', 'projects', 'tasks'):
        op.add_column(table, sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, server_default=None))
        op.create_index(f'ix_{table}_deleted_at', table, ['deleted_at'])
    # delegations.person_id: явный RESTRICT (раньше — без ondelete, что на Postgres то же самое, но теперь это зафиксировано)
    op.drop_constraint('delegations_person_id_fkey', 'delegations', type_='foreignkey')
    op.create_foreign_key('delegations_person_id_fkey', 'delegations', 'people', ['person_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    op.drop_constraint('delegations_person_id_fkey', 'delegations', type_='foreignkey')
    op.create_foreign_key('delegations_person_id_fkey', 'delegations', 'people', ['person_id'], ['id'])
    for table in ('tasks', 'projects', 'directions'):
        op.drop_index(f'ix_{table}_deleted_at', table_name=table)
        op.drop_column(table, 'deleted_at')
