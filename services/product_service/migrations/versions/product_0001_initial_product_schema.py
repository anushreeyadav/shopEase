"""initial product schema

Revision ID: product_0001
Revises: 
Create Date: 2026-10-30 11:42:06.413289

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
revision: str = 'product_0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('categories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['categories.id'], name=op.f('fk_categories_parent_id_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('name', name=op.f('uq_categories_name'))
    )
    op.create_index(op.f('ix_categories_parent_id'), 'categories', ['parent_id'], unique=False)
    op.create_table('products',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('sku', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('category_id', sa.Uuid(), nullable=True),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'ARCHIVED', name=op.f('ck_products_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('price >= 0', name=op.f('ck_products_price_non_negative')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products')),
    sa.UniqueConstraint('sku', name=op.f('uq_products_sku'))
    )
    op.create_index(op.f('ix_products_category_id'), 'products', ['category_id'], unique=False)
    op.create_index('ix_products_status_category_id', 'products', ['status', 'category_id'], unique=False)
    op.create_table('inventory',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_on_hand', sa.Integer(), nullable=False),
    sa.Column('quantity_reserved', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('quantity_on_hand >= 0', name=op.f('ck_inventory_on_hand_non_negative')),
    sa.CheckConstraint('quantity_reserved <= quantity_on_hand', name=op.f('ck_inventory_reserved_within_on_hand')),
    sa.CheckConstraint('quantity_reserved >= 0', name=op.f('ck_inventory_reserved_non_negative')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_inventory_product_id_products')),
    sa.PrimaryKeyConstraint('product_id', name=op.f('pk_inventory'))
    )
    op.create_table('inventory_movements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('quantity_change', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Enum('RESTOCK', 'RESERVE', 'CONFIRM', 'RELEASE', 'ADJUST', name=op.f('ck_inventory_movements_reason'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('reference_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('quantity_change <> 0', name=op.f('ck_inventory_movements_quantity_change_non_zero')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_inventory_movements_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_movements'))
    )
    op.create_index(op.f('ix_inventory_movements_product_id'), 'inventory_movements', ['product_id'], unique=False)
    op.create_index(op.f('ix_inventory_movements_reference_id'), 'inventory_movements', ['reference_id'], unique=False)
    op.create_table('stock_reservations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('RESERVED', 'CONFIRMED', 'RELEASED', 'EXPIRED', name=op.f('ck_stock_reservations_status'), native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.Column('updated_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_stock_reservations_quantity_positive')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_stock_reservations_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_reservations')),
    sa.UniqueConstraint('order_id', 'product_id', name=op.f('uq_stock_reservations_order_id_product_id'))
    )
    op.create_index(op.f('ix_stock_reservations_product_id'), 'stock_reservations', ['product_id'], unique=False)
    op.create_index('ix_stock_reservations_status_expires_at', 'stock_reservations', ['status', 'expires_at'], unique=False)


def downgrade() -> None:
    # Drop tables only, children first. Dropping a table removes its indexes; dropping an
    # index first fails on MySQL when a foreign key relies on it (error 1553).
    op.drop_table('stock_reservations')
    op.drop_table('inventory_movements')
    op.drop_table('inventory')
    op.drop_table('products')
    op.drop_table('categories')
