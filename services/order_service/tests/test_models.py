"""order_db model and schema behaviour, checked on SQLite (constraints are portable)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Order, OrderItem, OrderStatus, OrderStatusHistory
from app.orders import to_read

ADDRESS = {"line1": "12 MG Road", "city": "Bengaluru", "postal_code": "560001", "country": "IN"}


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_order(user_id: uuid.UUID, key: str = "key-1") -> Order:
    return Order(
        user_id=user_id,
        total_amount=Decimal("4998.00"),
        currency="INR",
        shipping_address_snapshot=ADDRESS,
        idempotency_key=key,
        request_fingerprint="f" * 64,
    )


def test_order_with_items_and_history_reads_back(session):
    order = make_order(uuid.uuid4())
    order.items.append(
        OrderItem(
            product_id=uuid.uuid4(),
            product_name_snapshot="Trail Running Shoe",
            unit_price_snapshot=Decimal("2499.00"),
            quantity=2,
        )
    )
    order.status_history.append(OrderStatusHistory(to_status=OrderStatus.PENDING, changed_by="system"))
    session.add(order)
    session.commit()

    body = to_read(order).model_dump(mode="json")
    assert body["status"] == "PENDING"
    assert body["total_amount"] == "4998.00"
    assert body["items"][0] == {
        "product_id": str(order.items[0].product_id),
        "name": "Trail Running Shoe",
        "unit_price": "2499.00",
        "quantity": 2,
        "line_total": "4998.00",
    }
    assert body["shipping_address"] == ADDRESS
    assert order.status_history[0].from_status is None


def test_idempotency_key_is_unique_per_user(session):
    user_id = uuid.uuid4()
    session.add_all([make_order(user_id), make_order(uuid.uuid4())])  # same key, other user: fine
    session.commit()
    session.add(make_order(user_id))
    with pytest.raises(IntegrityError):
        session.commit()


def test_item_quantity_must_be_positive(session):
    order = make_order(uuid.uuid4())
    order.items.append(
        OrderItem(product_id=uuid.uuid4(), product_name_snapshot="X", unit_price_snapshot=Decimal("1"), quantity=0)
    )
    session.add(order)
    with pytest.raises(IntegrityError, match="quantity"):
        session.commit()


def test_items_require_an_existing_order(session):
    session.add(
        OrderItem(
            order_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            product_name_snapshot="X",
            unit_price_snapshot=Decimal("1"),
            quantity=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
