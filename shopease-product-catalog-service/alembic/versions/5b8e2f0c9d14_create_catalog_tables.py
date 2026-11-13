"""create catalog tables

Revision ID: 5b8e2f0c9d14
Revises: (none, initial migration)

Creates the three tables of shopease_product_catalog_db:

- categories: unique name (uq_categories_name); name may not be blank.
- products: category_id -> categories.id (ON DELETE RESTRICT); unique sku (uq_products_sku);
  price and discount_price are DECIMAL(10, 2); CHECK constraints: price >= 0,
  discount_price NULL or 0 <= discount_price < price, stock_quantity >= 0, name and sku not blank.
  Indexes on name and category_id.
- inventory_transactions: product_id -> products.id (ON DELETE RESTRICT, so history is never
  lost); transaction_type IN or OUT; CHECK constraints: quantity > 0, both stock values >= 0,
  and updated_stock = previous_stock +/- quantity. Index (product_id, created_at) for history.

All timestamps are stored as UTC DATETIME values (see app/database/types.py).
CHECK constraints need MySQL 8.0.16 or later; the Docker image is MySQL 8.4.
downgrade() drops the tables, children first.

Create Date: 2026-11-12 11:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '5b8e2f0c9d14'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('categories',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("TRIM(name) <> ''", name=op.f('ck_categories_name_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('name', name=op.f('uq_categories_name'))
    )

    op.create_table('products',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('sku', sa.String(length=64), nullable=False),
    sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('discount_price', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('stock_quantity', sa.Integer(), server_default='0', nullable=False),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('brand', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('price >= 0', name=op.f('ck_products_price_non_negative')),
    sa.CheckConstraint('discount_price IS NULL OR (discount_price >= 0 AND discount_price < price)', name=op.f('ck_products_discount_price_valid')),
    sa.CheckConstraint('stock_quantity >= 0', name=op.f('ck_products_stock_quantity_non_negative')),
    sa.CheckConstraint("TRIM(name) <> ''", name=op.f('ck_products_name_not_blank')),
    sa.CheckConstraint("TRIM(sku) <> ''", name=op.f('ck_products_sku_not_blank')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products')),
    sa.UniqueConstraint('sku', name=op.f('uq_products_sku'))
    )
    op.create_index(op.f('ix_products_category_id'), 'products', ['category_id'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)

    op.create_table('inventory_transactions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('transaction_type', sa.Enum('IN', 'OUT', name='transaction_type', native_enum=False, create_constraint=True, length=3), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('previous_stock', sa.Integer(), nullable=False),
    sa.Column('updated_stock', sa.Integer(), nullable=False),
    sa.Column('remarks', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_inventory_transactions_quantity_positive')),
    sa.CheckConstraint('previous_stock >= 0', name=op.f('ck_inventory_transactions_previous_stock_non_negative')),
    sa.CheckConstraint('updated_stock >= 0', name=op.f('ck_inventory_transactions_updated_stock_non_negative')),
    sa.CheckConstraint("(transaction_type = 'IN' AND updated_stock = previous_stock + quantity) OR (transaction_type = 'OUT' AND updated_stock = previous_stock - quantity)", name=op.f('ck_inventory_transactions_stock_arithmetic')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_inventory_transactions_product_id_products'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_transactions'))
    )
    op.create_index(op.f('ix_inventory_transactions_product_id_created_at'), 'inventory_transactions', ['product_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('inventory_transactions')
    op.drop_table('products')
    op.drop_table('categories')
