"""initial order schema

Revision ID: order_0001
Revises: 
Create Date: 2026-10-30 11:42:07.953381

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
revision: str = 'order_0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('orders',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'AWAITING_PAYMENT', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED', name=op.f('ck_orders_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('shipping_address_snapshot', sa.JSON(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=True),
    sa.Column('payment_due_by', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('total_amount >= 0', name=op.f('ck_orders_total_amount_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('user_id', 'idempotency_key', name=op.f('uq_orders_user_id_idempotency_key'))
    )
    op.create_index(op.f('ix_orders_payment_id'), 'orders', ['payment_id'], unique=False)
    op.create_index('ix_orders_status_payment_due_by', 'orders', ['status', 'payment_due_by'], unique=False)
    op.create_index('ix_orders_user_id_created_at', 'orders', ['user_id', 'created_at'], unique=False)
    op.create_table('order_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('product_name_snapshot', sa.String(length=200), nullable=False),
    sa.Column('unit_price_snapshot', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_order_items_quantity_positive')),
    sa.CheckConstraint('unit_price_snapshot >= 0', name=op.f('ck_order_items_unit_price_non_negative')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items')),
    sa.UniqueConstraint('order_id', 'product_id', name=op.f('uq_order_items_order_id_product_id'))
    )
    op.create_index(op.f('ix_order_items_product_id'), 'order_items', ['product_id'], unique=False)
    op.create_table('order_status_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.Enum('PENDING', 'AWAITING_PAYMENT', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED', name=op.f('ck_order_status_history_from_status'), native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('to_status', sa.Enum('PENDING', 'AWAITING_PAYMENT', 'PAID', 'SHIPPED', 'DELIVERED', 'CANCELLED', name=op.f('ck_order_status_history_to_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('changed_by', sa.String(length=64), nullable=False),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('changed_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_status_history_order_id_orders')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_status_history'))
    )
    op.create_index('ix_order_status_history_order_id_changed_at', 'order_status_history', ['order_id', 'changed_at'], unique=False)


def downgrade() -> None:
    # Drop tables only, children first. Dropping a table removes its indexes; dropping an
    # index first fails on MySQL when a foreign key relies on it (error 1553).
    op.drop_table('order_status_history')
    op.drop_table('order_items')
    op.drop_table('orders')
