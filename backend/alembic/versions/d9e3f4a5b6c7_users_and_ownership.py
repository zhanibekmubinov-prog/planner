"""users + owner_id на направлениях/задачах/тулах/майндмапах, people.user_id, отчёт исполнителя.
Существующие данные передаются владельцу (OWNER_EMAIL), который создаётся здесь же.

Revision ID: d9e3f4a5b6c7
Revises: c8d2e3f4a5b6
"""
import os
from alembic import op
import sqlalchemy as sa


revision = 'd9e3f4a5b6c7'
down_revision = 'c8d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('ms_oid', sa.String(length=64), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('telegram_chat_id', sa.String(length=64), nullable=True),
        sa.Column('digest_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ms_oid'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    for table in ('directions', 'tasks', 'tools', 'mindmaps'):
        op.add_column(table, sa.Column('owner_id', sa.Integer(), nullable=True))
        op.create_foreign_key(f'fk_{table}_owner', table, 'users', ['owner_id'], ['id'], ondelete='SET NULL')
        op.create_index(f'ix_{table}_owner_id', table, ['owner_id'])
    op.add_column('people', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_people_user', 'people', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.create_unique_constraint('uq_people_user_id', 'people', ['user_id'])
    op.add_column('delegations', sa.Column('report', sa.Text(), nullable=True))
    op.add_column('delegations', sa.Column('assigned_notified_at', sa.DateTime(timezone=True), nullable=True))

    # --- данные: владелец и передача ему всего существующего ---
    owner_email = (os.environ.get('OWNER_EMAIL') or '').strip().lower()
    telegram = (os.environ.get('TELEGRAM_CHAT_ID') or '').strip() or None
    if owner_email:
        conn = op.get_bind()
        conn.execute(sa.text("INSERT INTO users (email, name, is_admin, telegram_chat_id) VALUES (:e, :n, true, :t)"),
                     {"e": owner_email, "n": owner_email.split('@')[0], "t": telegram})
        uid = conn.execute(sa.text("SELECT id FROM users WHERE email = :e"), {"e": owner_email}).scalar()
        for table in ('directions', 'tasks', 'tools', 'mindmaps'):
            conn.execute(sa.text(f"UPDATE {table} SET owner_id = :u WHERE owner_id IS NULL"), {"u": uid})
        # существующие поручения помечаем как уже уведомлённые — не рассылать задним числом
        conn.execute(sa.text("UPDATE delegations SET assigned_notified_at = now() WHERE assigned_notified_at IS NULL"))


def downgrade() -> None:
    op.drop_column('delegations', 'assigned_notified_at')
    op.drop_column('delegations', 'report')
    op.drop_constraint('uq_people_user_id', 'people', type_='unique')
    op.drop_constraint('fk_people_user', 'people', type_='foreignkey')
    op.drop_column('people', 'user_id')
    for table in ('directions', 'tasks', 'tools', 'mindmaps'):
        op.drop_index(f'ix_{table}_owner_id', table_name=table)
        op.drop_constraint(f'fk_{table}_owner', table, type_='foreignkey')
        op.drop_column(table, 'owner_id')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
