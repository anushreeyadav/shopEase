"""reconciliation and result-report tracking

Revision ID: payment_0002
Revises: payment_0001
Create Date: 2026-10-30 18:00:00

Reviewed: additive change to payments only.
- report_attempts / next_report_at: bounded retries of payment-result reports to order_service.
- reconcile_attempts / next_reconcile_at: bounded provider status checks for unknown outcomes.
- needs_manual_review: automatic handling stopped; a person must resolve the payment.
Existing rows get 0 / NULL / false. batch_alter_table issues plain ALTER TABLE on MySQL and
rebuilds the table on SQLite (tests). downgrade() drops the columns: disposable databases only.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'payment_0002'
down_revision: str | None = 'payment_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_DATETIME = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    with op.batch_alter_table('payments') as batch:
        batch.add_column(sa.Column('report_attempts', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('next_report_at', UTC_DATETIME, nullable=True))
        batch.add_column(sa.Column('reconcile_attempts', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('next_reconcile_at', UTC_DATETIME, nullable=True))
        batch.add_column(sa.Column('needs_manual_review', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.create_index(op.f('ix_payments_next_report_at'), ['next_report_at'], unique=False)
        batch.create_index('ix_payments_status_next_reconcile_at', ['status', 'next_reconcile_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('payments') as batch:
        batch.drop_index('ix_payments_status_next_reconcile_at')
        batch.drop_index(op.f('ix_payments_next_report_at'))
        batch.drop_column('needs_manual_review')
        batch.drop_column('next_reconcile_at')
        batch.drop_column('reconcile_attempts')
        batch.drop_column('next_report_at')
        batch.drop_column('report_attempts')
