"""initial auth schema

Revision ID: auth_0001
Revises: 
Create Date: 2026-10-30 11:42:03.291116

Reviewed: tables, columns, nullability, keys and indexes match app/models and
docs/database_ownership.md. Foreign keys stay inside this database; IDs owned by other
services are indexed plain columns. Enum CHECK constraint names are frozen with op.f() so
they don't depend on the model naming convention (MySQL requires CHECK names to be
unique per database). MySQL DDL is not transactional: a failure part-way leaves the
tables created so far; fix the cause, drop those tables by hand, then upgrade again.
downgrade() drops every table of this service and deletes its data: run it only on a
disposable database.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'auth_0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('auth_users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('customer', 'admin', name=op.f('ck_auth_users_role'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'DISABLED', name=op.f('ck_auth_users_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('failed_login_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('failed_login_attempts >= 0', name=op.f('ck_auth_users_failed_login_attempts_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_users')),
    sa.UniqueConstraint('email', name=op.f('uq_auth_users_email'))
    )
    op.create_table('service_clients',
    sa.Column('client_id', sa.String(length=64), nullable=False),
    sa.Column('secret_hash', sa.String(length=255), nullable=False),
    sa.Column('allowed_scopes', sa.JSON(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.PrimaryKeyConstraint('client_id', name=op.f('pk_service_clients'))
    )
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('revoked_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
    sa.Column('replaced_by_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.ForeignKeyConstraint(['replaced_by_id'], ['refresh_tokens.id'], name=op.f('fk_refresh_tokens_replaced_by_id_refresh_tokens'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['auth_users.id'], name=op.f('fk_refresh_tokens_user_id_auth_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_replaced_by_id'), 'refresh_tokens', ['replaced_by_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    # Drop tables only, children first. Dropping a table removes its indexes; dropping an
    # index first fails on MySQL when a foreign key relies on it (error 1553).
    op.drop_table('refresh_tokens')
    op.drop_table('service_clients')
    op.drop_table('auth_users')
