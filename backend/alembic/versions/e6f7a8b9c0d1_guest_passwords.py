"""v0.10.1: пароль гостя (scrypt-хеш), время установки и номер версии пароля.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('guests', sa.Column('password_hash', sa.String(length=300), nullable=True))
    op.add_column('guests', sa.Column('password_set_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('guests', sa.Column('password_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('guests', 'password_version')
    op.drop_column('guests', 'password_set_at')
    op.drop_column('guests', 'password_hash')
