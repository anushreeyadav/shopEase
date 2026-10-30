"""payment_db model and schema behaviour, checked on SQLite (constraints are portable)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Payment, PaymentStatus, PaymentStatusHistory, Refund, StatusSource
from app.payments import to_read
from app.schemas import RefundRead


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_payment(order_id: uuid.UUID, key: str, active: bool = True) -> Payment:
    return Payment(
        order_id=order_id,
        user_id=uuid.uuid4(),
        amount=Decimal("4998.00"),
        currency="INR",
        provider="mock",
        idempotency_key=key,
        request_fingerprint="f" * 64,
        active_order_id=order_id if active else None,
        card_brand="VISA",
        card_last4="4242",
    )


def test_payment_read_schema(session):
    payment = make_payment(uuid.uuid4(), "k1")
    session.add(payment)
    session.commit()
    body = to_read(payment).model_dump(mode="json")
    assert body["amount"] == "4998.00" and body["status"] == "INITIATED" and body["provider"] == "mock"


def test_only_one_active_payment_per_order(session):
    order_id = uuid.uuid4()
    session.add(make_payment(order_id, "k1"))
    session.commit()
    session.add(make_payment(order_id, "k2"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_a_new_attempt_is_allowed_once_the_previous_one_is_inactive(session):
    order_id = uuid.uuid4()
    failed = make_payment(order_id, "k1")
    session.add(failed)
    session.commit()
    failed.status, failed.active_order_id = PaymentStatus.FAILED, None
    session.add(make_payment(order_id, "k2"))
    session.commit()


def test_active_order_id_must_match_order_id(session):
    payment = make_payment(uuid.uuid4(), "k1")
    payment.active_order_id = uuid.uuid4()
    session.add(payment)
    with pytest.raises(IntegrityError, match="active_order_matches"):
        session.commit()


def test_idempotency_key_is_unique(session):
    session.add_all([make_payment(uuid.uuid4(), "same"), make_payment(uuid.uuid4(), "same")])
    with pytest.raises(IntegrityError):
        session.commit()


def test_provider_events_are_recorded_once(session):
    payment = make_payment(uuid.uuid4(), "k1")
    session.add(payment)
    session.flush()
    for _ in range(2):
        session.add(
            PaymentStatusHistory(
                payment_id=payment.id,
                from_status=PaymentStatus.PROCESSING,
                to_status=PaymentStatus.SUCCEEDED,
                source=StatusSource.WEBHOOK,
                provider_event_id="evt_123",
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_refunds_must_be_positive_and_belong_to_a_payment(session):
    payment = make_payment(uuid.uuid4(), "k1")
    session.add(payment)
    session.flush()
    refund = Refund(payment_id=payment.id, amount=Decimal("4998.00"), idempotency_key="r1")
    session.add(refund)
    session.commit()
    assert RefundRead.model_validate(refund).model_dump(mode="json")["status"] == "PENDING"

    session.add(Refund(payment_id=payment.id, amount=Decimal("0"), idempotency_key="r2"))
    with pytest.raises(IntegrityError, match="amount"):
        session.commit()
    session.rollback()
    session.add(Refund(payment_id=uuid.uuid4(), amount=Decimal("1"), idempotency_key="r3"))
    with pytest.raises(IntegrityError):
        session.commit()
