"""create user and address tables

Revision ID: 8c2e3b6d4acf
Revises: (none, initial migration)

Creates the two tables of shopease_user_db. Generated with --autogenerate and reviewed:
- user_profiles: includes is_active (local profile status). Unique constraint
  uq_user_profiles_auth_user_id: one profile per Authentication Service user.
- user_addresses: foreign key fk_user_addresses_user_id_user_profiles to user_profiles.id,
  ON DELETE CASCADE, and index ix_user_addresses_user_id.
- gender and address_type: VARCHAR with CHECK constraints (non-native enums).
- default_marker: stored generated column (1 or NULL). Its unique key with user_id allows
  one default address per user.

downgrade() drops only these two tables, child first. Dropping a table also drops its
indexes and constraints. The alembic_version table is left for Alembic to manage.
Create Date: 2026-11-10 10:34:48.320338
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '8c2e3b6d4acf'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('user_profiles',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('auth_user_id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('phone_number', sa.String(length=20), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('gender', sa.Enum('MALE', 'FEMALE', 'OTHER', 'PREFER_NOT_TO_SAY', name='gender', native_enum=False, create_constraint=True, length=20), nullable=True),
    sa.Column('profile_image', sa.String(length=500), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_profiles')),
    sa.UniqueConstraint('auth_user_id', name=op.f('uq_user_profiles_auth_user_id'))
    )
    op.create_table('user_addresses',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('address_type', sa.Enum('HOME', 'WORK', 'OTHER', name='address_type', native_enum=False, create_constraint=True, length=20), server_default='HOME', nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('phone_number', sa.String(length=20), nullable=False),
    sa.Column('address_line_1', sa.String(length=255), nullable=False),
    sa.Column('address_line_2', sa.String(length=255), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('state', sa.String(length=100), nullable=False),
    sa.Column('country', sa.String(length=100), nullable=False),
    sa.Column('postal_code', sa.String(length=20), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('default_marker', sa.Integer(), sa.Computed('CASE WHEN is_default THEN 1 ELSE NULL END', persisted=True), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id'], name=op.f('fk_user_addresses_user_id_user_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_addresses')),
    sa.UniqueConstraint('user_id', 'default_marker', name='uq_user_addresses_one_default_per_user')
    )
    op.create_index(op.f('ix_user_addresses_user_id'), 'user_addresses', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('user_addresses')
    op.drop_table('user_profiles')
