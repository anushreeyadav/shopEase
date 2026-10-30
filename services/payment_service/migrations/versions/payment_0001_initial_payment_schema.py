"""initial payment schema

Revision ID: payment_0001
Revises: 
Create Date: 2026-10-30 11:42:09.514671

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
revision: str = 'payment_0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('payments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('INITIATED', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'REFUNDED', name=op.f('ck_payments_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_txn_ref', sa.String(length=128), nullable=True),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('active_order_id', sa.Uuid(), nullable=True),
    sa.Column('card_brand', sa.String(length=20), nullable=True),
    sa.Column('card_last4', sa.String(length=4), nullable=True),
    sa.Column('failure_reason', sa.String(length=255), nullable=True),
    sa.Column('result_reported_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('active_order_id IS NULL OR active_order_id = order_id', name=op.f('ck_payments_active_order_matches')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_payments_amount_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
    sa.UniqueConstraint('active_order_id', name=op.f('uq_payments_active_order_id')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_payments_idempotency_key')),
    sa.UniqueConstraint('provider', 'provider_txn_ref', name=op.f('uq_payments_provider_provider_txn_ref'))
    )
    op.create_index(op.f('ix_payments_order_id'), 'payments', ['order_id'], unique=False)
    op.create_index('ix_payments_status_updated_at', 'payments', ['status', 'updated_at'], unique=False)
    op.create_index(op.f('ix_payments_user_id'), 'payments', ['user_id'], unique=False)
    op.create_table('payment_status_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.Enum('INITIATED', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'REFUNDED', name=op.f('ck_payment_status_history_from_status'), native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('to_status', sa.Enum('INITIATED', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'REFUNDED', name=op.f('ck_payment_status_history_to_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('source', sa.Enum('API', 'WEBHOOK', 'RECONCILIATION', name=op.f('ck_payment_status_history_source'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider_event_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_payment_status_history_payment_id_payments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_status_history')),
    sa.UniqueConstraint('provider_event_id', name=op.f('uq_payment_status_history_provider_event_id'))
    )
    op.create_index(op.f('ix_payment_status_history_payment_id'), 'payment_status_history', ['payment_id'], unique=False)
    op.create_table('refunds',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED', name=op.f('ck_refunds_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider_refund_ref', sa.String(length=128), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('amount > 0', name=op.f('ck_refunds_amount_positive')),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_refunds_payment_id_payments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refunds')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_refunds_idempotency_key'))
    )
    op.create_index(op.f('ix_refunds_payment_id'), 'refunds', ['payment_id'], unique=False)


def downgrade() -> None:
    # Drop tables only, children first. Dropping a table removes its indexes; dropping an
    # index first fails on MySQL when a foreign key relies on it (error 1553).
    op.drop_table('refunds')
    op.drop_table('payment_status_history')
    op.drop_table('payments')
