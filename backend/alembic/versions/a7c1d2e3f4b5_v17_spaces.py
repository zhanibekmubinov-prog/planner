"""v1.7: слои «Личное» / «Организация»

Добавляет `directions.space`, `directions.space_pinned` и `tasks.space`, после чего
раскладывает существующие направления по слоям по правилу владельца (2026-10-05):
есть доступ у кого-то ещё (шара на само направление, на его проект или задачу) или
есть хоть одно поручение по его задачам → «Организация»; всё остальное → «Личное».

`space_pinned` у всех остаётся False: разложили автоматически, и дальше автоправило
работает как обычно, пока владелец сам не перенесёт направление руками.

Revision ID: a7c1d2e3f4b5
Revises: f2b6c7d8e9a0
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c1d2e3f4b5"
down_revision = "f2b6c7d8e9a0"
branch_labels = None
depends_on = None


BACKFILL = """
UPDATE directions SET space = 'org'
WHERE EXISTS (
        SELECT 1 FROM shares s
        WHERE s.entity_type = 'direction' AND s.entity_id = directions.id)
   OR EXISTS (
        SELECT 1 FROM shares s JOIN projects p ON p.id = s.entity_id
        WHERE s.entity_type = 'project' AND p.direction_id = directions.id)
   OR EXISTS (
        SELECT 1 FROM shares s JOIN task_directions td ON td.task_id = s.entity_id
        WHERE s.entity_type = 'task' AND td.direction_id = directions.id)
   OR EXISTS (
        SELECT 1 FROM delegations dl JOIN task_directions td ON td.task_id = dl.task_id
        WHERE td.direction_id = directions.id)
"""


def upgrade() -> None:
    op.add_column("directions", sa.Column("space", sa.String(length=8), nullable=False, server_default="personal"))
    op.add_column("directions", sa.Column("space_pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_directions_space", "directions", ["space"])
    op.add_column("tasks", sa.Column("space", sa.String(length=8), nullable=True))
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_column("tasks", "space")
    op.drop_index("ix_directions_space", table_name="directions")
    op.drop_column("directions", "space_pinned")
    op.drop_column("directions", "space")
