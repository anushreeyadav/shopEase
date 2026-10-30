"""inventory movement audit columns

Revision ID: product_0002
Revises: product_0001
Create Date: 2026-10-30 14:00:00

Reviewed: additive change to inventory_movements only. A reservation changes the reserved
count, not stock on hand, so one signed quantity can't describe every movement. Adds
reserved_change, the levels after the change, the actor and a note. Existing rows get
reserved_change = 0 and actor = 'system'; their *_after columns stay NULL (unknown).
The CHECK "quantity_change <> 0" becomes "quantity_change <> 0 OR reserved_change <> 0".
batch_alter_table issues plain ALTER TABLE on MySQL and rebuilds the table on SQLite (tests).
downgrade() removes the columns and their data: run it only on a disposable database.
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'product_0002'
down_revision: str | None = 'product_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('inventory_movements') as batch:
        batch.add_column(sa.Column('reserved_change', sa.Integer(), server_default='0', nullable=False))
        batch.add_column(sa.Column('on_hand_after', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('reserved_after', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('actor', sa.String(length=64), server_default='system', nullable=False))
        batch.add_column(sa.Column('note', sa.String(length=255), nullable=True))
        batch.drop_constraint(op.f('ck_inventory_movements_quantity_change_non_zero'), type_='check')
        batch.create_check_constraint(
            op.f('ck_inventory_movements_has_change'), 'quantity_change <> 0 OR reserved_change <> 0'
        )
        batch.create_index(
            'ix_inventory_movements_product_id_created_at', ['product_id', 'created_at'], unique=False
        )


def downgrade() -> None:
    # Rows recording only a reserved change would violate the restored check: remove them first.
    op.execute("DELETE FROM inventory_movements WHERE quantity_change = 0")
    with op.batch_alter_table('inventory_movements') as batch:
        batch.drop_index('ix_inventory_movements_product_id_created_at')
        batch.drop_constraint(op.f('ck_inventory_movements_has_change'), type_='check')
        batch.create_check_constraint(
            op.f('ck_inventory_movements_quantity_change_non_zero'), 'quantity_change <> 0'
        )
        batch.drop_column('note')
        batch.drop_column('actor')
        batch.drop_column('reserved_after')
        batch.drop_column('on_hand_after')
        batch.drop_column('reserved_change')
