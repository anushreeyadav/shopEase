"""checkout tracking columns

Revision ID: order_0002
Revises: order_0001
Create Date: 2026-10-30 16:00:00

Reviewed: additive change to orders only.
- payment_status: latest outcome reported by payment_service (NONE for existing rows).
- cancel_reason: why an order was cancelled (OUT_OF_STOCK, PAYMENT_TIMEOUT, ...).
- release_pending: stock may still be reserved at product_service; the recovery job retries.
- index (status, created_at) for finding PENDING orders abandoned mid-checkout.
batch_alter_table issues plain ALTER TABLE on MySQL and rebuilds the table on SQLite (tests).
downgrade() removes the columns and their data: run it only on a disposable database.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'order_0002'
down_revision: str | None = 'order_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        # VARCHAR plus a named CHECK, like the model's enum (an Enum type with its own
        # constraint can't be added inside SQLite's batch rebuild).
        batch.add_column(sa.Column('payment_status', sa.String(length=32), server_default='NONE', nullable=False))
        batch.create_check_constraint(
            op.f('ck_orders_payment_status'),
            "payment_status IN ('NONE', 'PROCESSING', 'FAILED', 'SUCCEEDED', 'REFUNDED')",
        )
        batch.add_column(sa.Column('cancel_reason', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('release_pending', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.create_index(op.f('ix_orders_release_pending'), ['release_pending'], unique=False)
        batch.create_index('ix_orders_status_created_at', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('orders') as batch:
        batch.drop_index('ix_orders_status_created_at')
        batch.drop_index(op.f('ix_orders_release_pending'))
        batch.drop_column('release_pending')
        batch.drop_column('cancel_reason')
        batch.drop_constraint(op.f('ck_orders_payment_status'), type_='check')
        batch.drop_column('payment_status')
