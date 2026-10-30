"""product_db model and schema behaviour, checked on SQLite (constraints are portable)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models import Base, Inventory, InventoryMovement, MovementReason, Product, StockReservation
from app.catalog import product_detail
from app.schemas import InventoryRead


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def product(session) -> Product:
    product = Product(sku="TRS-001", name="Trail Running Shoe", price=Decimal("2499.00"))
    session.add(product)
    session.flush()
    session.add(Inventory(product_id=product.id, quantity_on_hand=10))
    session.commit()
    return product


def test_product_read_serializes_money_as_string(session, product):
    body = product_detail(session, product).model_dump(mode="json")
    assert body["price"] == "2499.00" and body["currency"] == "INR" and body["status"] == "ACTIVE"


def test_negative_price_is_rejected(session):
    session.add(Product(sku="BAD-1", name="Bad", price=Decimal("-1.00")))
    with pytest.raises(IntegrityError, match="price"):
        session.commit()


def test_unknown_status_is_rejected(session):
    session.add(Product(sku="BAD-2", name="Bad", price=Decimal("1.00"), status="DELETED"))
    with pytest.raises(StatementError):
        session.commit()


def test_reserved_stock_cannot_exceed_stock_on_hand(session, product):
    inventory = session.get(Inventory, product.id)
    inventory.quantity_reserved = 11
    with pytest.raises(IntegrityError, match="reserved_within_on_hand"):
        session.commit()


def test_inventory_updates_use_optimistic_locking(engine, product):
    with Session(engine) as first, Session(engine) as second:
        a = first.get(Inventory, product.id)
        b = second.get(Inventory, product.id)
        a.quantity_reserved = 2
        first.commit()
        assert a.version == 2
        b.quantity_reserved = 3  # based on a stale read
        with pytest.raises(StaleDataError):
            second.commit()
    assert InventoryRead.model_validate(a).quantity_available == 8


def test_reservations_are_unique_per_order_and_product(session, product):
    order_id = uuid.uuid4()  # owned by order_service: no foreign key
    expires = datetime.now(UTC) + timedelta(minutes=15)
    session.add_all(
        [
            StockReservation(order_id=order_id, product_id=product.id, quantity=1, expires_at=expires),
            StockReservation(order_id=order_id, product_id=product.id, quantity=1, expires_at=expires),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_movement_log_rejects_zero_changes(session, product):
    session.add(InventoryMovement(product_id=product.id, quantity_change=0, reason=MovementReason.ADJUST))
    with pytest.raises(IntegrityError, match="has_change"):
        session.commit()


def test_enum_values_are_stored_as_readable_strings(session, product):
    session.add(InventoryMovement(product_id=product.id, quantity_change=10, reason=MovementReason.RESTOCK))
    session.commit()
    assert session.execute(text("SELECT reason FROM inventory_movements")).scalar_one() == "RESTOCK"
