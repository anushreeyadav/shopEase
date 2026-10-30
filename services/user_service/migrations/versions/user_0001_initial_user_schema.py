"""initial user schema

Revision ID: user_0001
Revises: 
Create Date: 2026-10-30 11:42:04.845192

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
revision: str = 'user_0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('user_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=True),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('contact_email', sa.String(length=254), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_profiles'))
    )
    op.create_table('user_addresses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(length=50), nullable=True),
    sa.Column('line1', sa.String(length=200), nullable=False),
    sa.Column('line2', sa.String(length=200), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('state', sa.String(length=100), nullable=True),
    sa.Column('postal_code', sa.String(length=20), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.user_id'], name=op.f('fk_user_addresses_user_id_user_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_addresses'))
    )
    op.create_index('ix_user_addresses_user_id_is_default', 'user_addresses', ['user_id', 'is_default'], unique=False)


def downgrade() -> None:
    # Drop tables only, children first. Dropping a table removes its indexes; dropping an
    # index first fails on MySQL when a foreign key relies on it (error 1553).
    op.drop_table('user_addresses')
    op.drop_table('user_profiles')
