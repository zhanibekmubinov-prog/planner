"""v0.10: внешние участники — список гостей и одноразовые ссылки входа.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'guests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('invited_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_guests_email', 'guests', ['email'], unique=True)

    op.create_table(
        'guest_login_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_guest_login_tokens_email', 'guest_login_tokens', ['email'])
    op.create_index('ix_guest_login_tokens_token_hash', 'guest_login_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_guest_login_tokens_token_hash', table_name='guest_login_tokens')
    op.drop_index('ix_guest_login_tokens_email', table_name='guest_login_tokens')
    op.drop_table('guest_login_tokens')
    op.drop_index('ix_guests_email', table_name='guests')
    op.drop_table('guests')
