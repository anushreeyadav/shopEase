"""rename WORK address type to OFFICE

Revision ID: 4f1a9d27c5e3
Revises: 8c2e3b6d4acf

The address types are now HOME, OFFICE and OTHER. Written by hand: autogenerate does not
compare CHECK constraints, so it cannot detect a changed enum value.

upgrade() drops the CHECK constraint, converts existing WORK rows to OFFICE, and recreates
the constraint with the new values. downgrade() does the reverse, so no row is left with a
value the constraint would reject.
Create Date: 2026-11-11 10:05:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = '4f1a9d27c5e3'
down_revision: str | None = '8c2e3b6d4acf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = 'ck_user_addresses_address_type'


def _replace_address_type(old: str, new: str, allowed: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(CONSTRAINT), 'user_addresses', type_='check')
    op.execute(f"UPDATE user_addresses SET address_type = '{new}' WHERE address_type = '{old}'")
    values = ', '.join(f"'{value}'" for value in allowed)
    op.create_check_constraint(op.f(CONSTRAINT), 'user_addresses', f'address_type IN ({values})')


def upgrade() -> None:
    _replace_address_type('WORK', 'OFFICE', ('HOME', 'OFFICE', 'OTHER'))


def downgrade() -> None:
    _replace_address_type('OFFICE', 'WORK', ('HOME', 'WORK', 'OTHER'))
