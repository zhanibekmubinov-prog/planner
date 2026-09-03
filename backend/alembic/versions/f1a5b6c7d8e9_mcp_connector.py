"""MCP-коннектор для Claude: OAuth-клиенты, ожидающие авторизации, коды и токены.

Revision ID: f1a5b6c7d8e9
Revises: e0f4a5b6c7d8
"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a5b6c7d8e9'
down_revision = 'e0f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('mcp_clients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('client_name', sa.String(length=128), nullable=False),
        sa.Column('redirect_uris', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_mcp_clients_client_id', 'mcp_clients', ['client_id'], unique=True)

    op.create_table('mcp_pending_auth',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('redirect_uri', sa.String(length=1000), nullable=False),
        sa.Column('state', sa.String(length=500), nullable=True),
        sa.Column('code_challenge', sa.String(length=128), nullable=False),
        sa.Column('scope', sa.String(length=200), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mcp_pending_auth_key', 'mcp_pending_auth', ['key'], unique=True)

    op.create_table('mcp_auth_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('redirect_uri', sa.String(length=1000), nullable=False),
        sa.Column('code_challenge', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_mcp_auth_codes_code_hash', 'mcp_auth_codes', ['code_hash'], unique=True)

    op.create_table('mcp_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('access_token_hash', sa.String(length=64), nullable=False),
        sa.Column('refresh_token_hash', sa.String(length=64), nullable=False),
        sa.Column('client_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('refresh_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_mcp_tokens_access_token_hash', 'mcp_tokens', ['access_token_hash'], unique=True)
    op.create_index('ix_mcp_tokens_refresh_token_hash', 'mcp_tokens', ['refresh_token_hash'], unique=True)
    op.create_index('ix_mcp_tokens_user_id', 'mcp_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('mcp_tokens')
    op.drop_table('mcp_auth_codes')
    op.drop_table('mcp_pending_auth')
    op.drop_table('mcp_clients')
