"""v1.8: совместная правка майндмапов — номер правки карты

`mindmaps.version` растёт на каждую принятую пачку операций и на полную замену карты.
По нему участники совместной правки понимают, не пропустили ли они чужие изменения.
Доступ к карте (entity_type = 'mindmap' в `shares`) новой схемы не требует: колонка
строковая.

Revision ID: b8e4f5a6c7d9
Revises: a7c1d2e3f4b5
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e4f5a6c7d9"
down_revision = "a7c1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mindmaps", sa.Column("version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("mindmaps", "version")
