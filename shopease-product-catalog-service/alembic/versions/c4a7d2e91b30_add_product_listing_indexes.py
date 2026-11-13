"""add product listing indexes

Revision ID: c4a7d2e91b30
Revises: 5b8e2f0c9d14

Indexes for GET /api/products/ (Task 8):

- ix_products_price: the min_price / max_price filter and sort_by=price.
- ix_products_created_at: sort_by=created_at (newest or oldest first).

Name and category already have indexes (ix_products_name, ix_products_category_id), and SKU has
the unique index uq_products_sku. Only indexes are added; no data is changed.

Create Date: 2026-11-12 16:00:00
"""

from collections.abc import Sequence

from alembic import op


revision: str = 'c4a7d2e91b30'
down_revision: str | None = '5b8e2f0c9d14'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f('ix_products_price'), 'products', ['price'], unique=False)
    op.create_index('ix_products_created_at', 'products', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_products_created_at', table_name='products')
    op.drop_index(op.f('ix_products_price'), table_name='products')
