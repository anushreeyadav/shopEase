"""Order rules and checkout coordination (docs/order_workflow.md).

Two rules shape this module:
1. No database transaction stays open across a network call. Each local step is a short
   transaction that locks the order row, re-checks its status, changes it and commits.
2. product_service's reservation is the arbiter between "confirm" (paid) and "release"
   (cancelled/expired): only one of them can succeed, so concurrent payment results,
   cancellations and the expiry job can't both win.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.clients import Deadline, DependencyError, ServiceClients
from app.config import Settings
from app.models import Order, OrderItem, OrderStatus, PaymentStatus
from app.models.base import utcnow
from app.schemas import (
    OrderCreate,
    OrderItemRead,
    OrderRead,
    OrderSummary,
    PayableRead,
    PaymentResult,
    StatusChangeRead,
)
from app.state import invalid_transition, transition
from shopease_shared import ShopEaseError
from shopease_shared.security import Principal

logger = logging.getLogger(__name__)
S = OrderStatus
CENT = Decimal("0.01")

# Cancel reasons meaning "the order was never placed" (creation failed after the row existed).
CREATION_FAILURES = {
    "OUT_OF_STOCK", "PRODUCT_UNAVAILABLE", "PRODUCT_NOT_FOUND",
    "DEPENDENCY_TIMEOUT", "DEPENDENCY_UNAVAILABLE", "STUCK_PENDING",
}


# --- Errors ------------------------------------------------------------------------------


def order_not_found(order_id: uuid.UUID) -> ShopEaseError:
    return ShopEaseError(404, "ORDER_NOT_FOUND", f"Order {order_id} was not found.")


def dependency_error(exc: DependencyError, *, placed_message: str) -> ShopEaseError:
    if exc.kind == "timeout":
        return ShopEaseError(504, "DEPENDENCY_TIMEOUT", placed_message, headers={"Retry-After": "2"})
    return ShopEaseError(503, "DEPENDENCY_UNAVAILABLE", placed_message, headers={"Retry-After": "2"})


def _downstream_error(response) -> dict:
    try:
        return response.json().get("error", {})
    except ValueError:
        return {}


# --- Reading -----------------------------------------------------------------------------


def _load(session: Session, order_id: uuid.UUID, lock: bool = False) -> Order | None:
    query = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.status_history))
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return session.scalars(query).one_or_none()


def get_visible_order(session: Session, order_id: uuid.UUID, user: Principal) -> Order:
    """Owner or admin; someone else's order is reported as not found (no ID probing)."""
    order = _load(session, order_id)
    if order is None or (order.user_id != user.user_id and not user.is_admin):
        raise order_not_found(order_id)
    return order


def to_read(order: Order) -> OrderRead:
    history = sorted(order.status_history, key=lambda h: (h.changed_at, h.id))
    return OrderRead(
        order_id=order.id,
        user_id=order.user_id,
        status=order.status,
        payment_status=order.payment_status,
        items=[
            OrderItemRead(
                product_id=i.product_id,
                name=i.product_name_snapshot,
                unit_price=i.unit_price_snapshot,
                quantity=i.quantity,
                line_total=(i.unit_price_snapshot * i.quantity).quantize(CENT),
            )
            for i in sorted(order.items, key=lambda i: str(i.product_id))
        ],
        total_amount=order.total_amount,
        currency=order.currency,
        shipping_address=order.shipping_address_snapshot,
        payment_id=order.payment_id,
        payment_due_by=order.payment_due_by,
        cancel_reason=order.cancel_reason,
        status_history=[
            StatusChangeRead(from_status=h.from_status, to_status=h.to_status, reason=h.reason, changed_at=h.changed_at)
            for h in history
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def list_orders(
    session: Session,
    user: Principal,
    *,
    user_id: uuid.UUID | None,
    status: OrderStatus | None,
    created_from,
    created_to,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[OrderSummary], int]:
    query = select(Order)
    if not user.is_admin:
        if user_id is not None:
            raise ShopEaseError(403, "FORBIDDEN", "Only admins can filter by user_id.")
        query = query.where(Order.user_id == user.user_id)
    elif user_id is not None:
        query = query.where(Order.user_id == user_id)
    if status is not None:
        query = query.where(Order.status == status)
    if created_from is not None:
        query = query.where(Order.created_at >= created_from)
    if created_to is not None:
        query = query.where(Order.created_at < created_to)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    order_by = (Order.created_at.desc(), Order.id) if sort == "-created_at" else (Order.created_at, Order.id)
    orders = session.scalars(
        query.options(selectinload(Order.items)).order_by(*order_by).limit(limit).offset(offset)
    ).all()
    return [
        OrderSummary(
            order_id=o.id,
            status=o.status,
            payment_status=o.payment_status,
            total_amount=o.total_amount,
            currency=o.currency,
            item_count=sum(i.quantity for i in o.items),
            created_at=o.created_at,
        )
        for o in orders
    ], total


# --- Creating an order (checkout steps 4-6) ------------------------------------------------


def fingerprint(body: OrderCreate) -> str:
    canonical = {
        "items": sorted([str(i.product_id), i.quantity] for i in body.items),
        "shipping_address_id": str(body.shipping_address_id),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def _find_by_key(session: Session, user_id: uuid.UUID, key: str) -> Order | None:
    order_id = session.scalar(select(Order.id).where(Order.user_id == user_id, Order.idempotency_key == key))
    return _load(session, order_id) if order_id else None


def _replay(order: Order, request_fingerprint: str) -> Order:
    """Answer a repeated Idempotency-Key the way the first request was answered."""
    if order.request_fingerprint != request_fingerprint:
        raise ShopEaseError(
            409, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different request."
        )
    if order.status is S.PENDING:
        raise ShopEaseError(
            409, "REQUEST_IN_PROGRESS", "The first request with this key is still being processed.",
            headers={"Retry-After": "2"},
        )
    never_placed = order.status is S.CANCELLED and order.cancel_reason in CREATION_FAILURES and not any(
        h.to_status is S.AWAITING_PAYMENT for h in order.status_history
    )
    if never_placed:
        reason = order.cancel_reason
        if reason in ("OUT_OF_STOCK", "PRODUCT_UNAVAILABLE"):
            raise ShopEaseError(409, reason, "The order could not be placed: some items are not available.")
        if reason == "PRODUCT_NOT_FOUND":
            raise ShopEaseError(404, reason, "The order could not be placed: some products do not exist.")
        raise ShopEaseError(
            503, "ORDER_NOT_PLACED",
            "The order could not be placed because a dependency failed. Retry with a new Idempotency-Key.",
        )
    return order


def _price_lines(clients: ServiceClients, body: OrderCreate, deadline: Deadline) -> tuple[list[dict], Decimal, str]:
    """Authoritative names, prices and availability from product_service; totals computed here."""
    requested = {item.product_id: item.quantity for item in body.items}
    try:
        response = clients.price_check(list(requested), deadline)
    except DependencyError as exc:
        raise dependency_error(exc, placed_message="The catalog is temporarily unavailable. Please retry.") from exc
    if response.status_code != 200:
        raise dependency_error(DependencyError("product_service", "bad_response"),
                               placed_message="The catalog returned an unexpected answer. Please retry.")
    data = response.json()
    if data["missing"]:
        raise ShopEaseError(
            404, "PRODUCT_NOT_FOUND", "Some products do not exist.",
            [{"field": "body.items", "issue": f"unknown product {pid}"} for pid in data["missing"]],
        )
    by_id = {uuid.UUID(item["product_id"]): item for item in data["items"]}
    problems, unavailable = [], []
    for index, item in enumerate(body.items):
        info = by_id[item.product_id]
        if info["status"] != "ACTIVE":
            unavailable.append({"field": f"items[{index}]", "issue": f"'{info['name']}' is no longer sold"})
        elif info["available_quantity"] < item.quantity:
            problems.append({
                "field": f"items[{index}].quantity",
                "issue": f"exceeds available stock ({max(info['available_quantity'], 0)})",
            })
    if unavailable:
        raise ShopEaseError(409, "PRODUCT_UNAVAILABLE", "Some products are no longer sold.", unavailable)
    if problems:
        raise ShopEaseError(409, "OUT_OF_STOCK", "Not enough stock for some items.", problems)
    currencies = {by_id[pid]["currency"] for pid in requested}
    if len(currencies) != 1:
        raise ShopEaseError(409, "MIXED_CURRENCY", "All items in one order must use the same currency.")

    lines, total = [], Decimal("0.00")
    for item in body.items:
        info = by_id[item.product_id]
        unit_price = Decimal(str(info["price"])).quantize(CENT, rounding=ROUND_HALF_UP)
        line_total = (unit_price * item.quantity).quantize(CENT, rounding=ROUND_HALF_UP)
        total += line_total
        lines.append({"product_id": item.product_id, "name": info["name"], "unit_price": unit_price,
                      "quantity": item.quantity})
    return lines, total, currencies.pop()


def _address_snapshot(
    clients: ServiceClients, user_id: uuid.UUID, address_id: uuid.UUID, user_token: str, deadline: Deadline
) -> dict[str, Any]:
    try:
        response = clients.address(user_id, address_id, user_token, deadline)
    except DependencyError as exc:
        raise dependency_error(exc, placed_message="Addresses are temporarily unavailable. Please retry.") from exc
    if response.status_code == 404:
        raise ShopEaseError(
            404, "ADDRESS_NOT_FOUND", "The shipping address was not found.",
            [{"field": "body.shipping_address_id", "issue": "unknown address"}],
        )
    if response.status_code != 200:
        logger.error("address lookup rejected", extra={"status": response.status_code})
        raise dependency_error(DependencyError("user_service", "bad_response"),
                               placed_message="Addresses are temporarily unavailable. Please retry.")
    address = response.json()
    fields = ("label", "line1", "line2", "city", "state", "postal_code", "country")
    return {f: address.get(f) for f in fields}


def _cancel_unplaced(
    session: Session, clients: ServiceClients, order_id: uuid.UUID, reason: str, release: bool
) -> None:
    """Compensation for a reservation whose outcome is unknown: release it (idempotent), then cancel."""
    release_pending = False
    if release:
        try:
            response = clients.release(order_id, Deadline.after(2.0))
            release_pending = response.status_code != 200
        except DependencyError:
            release_pending = True  # the recovery job retries; the reservation also expires
    order = _load(session, order_id, lock=True)
    if order is not None and order.status is S.PENDING:
        transition(session, order, S.CANCELLED, "system:checkout", reason)
        order.release_pending = release_pending
    session.commit()


def create_order(
    session: Session,
    clients: ServiceClients,
    settings: Settings,
    user: Principal,
    user_token: str,
    body: OrderCreate,
    idempotency_key: str,
) -> tuple[Order, bool]:
    """Returns (order, created). created=False for a replay of the same Idempotency-Key."""
    deadline = Deadline.after(settings.create_deadline_seconds)
    request_fingerprint = fingerprint(body)
    existing = _find_by_key(session, user.user_id, idempotency_key)
    session.rollback()  # end the read transaction before any network call
    if existing is not None:
        return _replay(existing, request_fingerprint), False

    # Steps 5a-5b: validate with current data. Nothing is stored yet, so failures here leave
    # no trace and the client may retry with the same key.
    lines, total, currency = _price_lines(clients, body, deadline)
    address = _address_snapshot(clients, user.user_id, body.shipping_address_id, user_token, deadline)

    # Step 4: persist the order as PENDING (one short transaction).
    order = Order(
        id=uuid.uuid4(),
        user_id=user.user_id,
        total_amount=total,
        currency=currency,
        shipping_address_snapshot=address,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    for line in lines:
        order.items.append(
            OrderItem(product_id=line["product_id"], product_name_snapshot=line["name"],
                      unit_price_snapshot=line["unit_price"], quantity=line["quantity"])
        )
    transition(session, order, S.PENDING, str(user.user_id), "order submitted")
    session.add(order)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request with the same key won: answer as a replay.
        session.rollback()
        existing = _find_by_key(session, user.user_id, idempotency_key)
        session.rollback()
        if existing is None:
            raise
        return _replay(existing, request_fingerprint), False

    # Step 6: reserve stock (idempotent per order_id at product_service).
    items = [{"product_id": str(line["product_id"]), "quantity": line["quantity"]} for line in lines]
    try:
        response = clients.reserve(order.id, items, deadline)
    except DependencyError as exc:
        # Outcome unknown: stock may or may not be held. Release (idempotent) and cancel.
        reason = "DEPENDENCY_TIMEOUT" if exc.kind == "timeout" else "DEPENDENCY_UNAVAILABLE"
        _cancel_unplaced(session, clients, order.id, reason, release=True)
        logger.warning("reservation failed; order cancelled", extra={"order_id": str(order.id), "kind": exc.kind})
        raise dependency_error(
            exc, placed_message="Inventory did not respond, so the order was not placed. "
                                "Retry with a new Idempotency-Key.",
        ) from exc

    if response.status_code in (200, 201):
        reservation = response.json()
        locked = _load(session, order.id, lock=True)
        transition(session, locked, S.AWAITING_PAYMENT, "system:checkout", "stock reserved")
        locked.payment_due_by = datetime.fromisoformat(reservation["expires_at"].replace("Z", "+00:00"))
        session.commit()
        logger.info("order placed", extra={"order_id": str(order.id)})
        return locked, True

    error = _downstream_error(response)
    code = error.get("code", "")
    if response.status_code in (404, 409) and code in ("OUT_OF_STOCK", "PRODUCT_UNAVAILABLE", "PRODUCT_NOT_FOUND"):
        _cancel_unplaced(session, clients, order.id, code, release=False)  # nothing was reserved
        raise ShopEaseError(response.status_code, code, error.get("message", "Stock is not available."),
                            error.get("details"))
    # Any other answer: treat the reservation as unknown and compensate.
    _cancel_unplaced(session, clients, order.id, "DEPENDENCY_UNAVAILABLE", release=True)
    logger.error("unexpected reservation answer", extra={"order_id": str(order.id), "status": response.status_code})
    raise ShopEaseError(503, "DEPENDENCY_UNAVAILABLE",
                        "Inventory returned an unexpected answer, so the order was not placed. "
                        "Retry with a new Idempotency-Key.")


# --- Cancelling and fulfilment -----------------------------------------------------------------


def cancel_order(session: Session, clients: ServiceClients, order_id: uuid.UUID, user: Principal) -> Order:
    order = get_visible_order(session, order_id, user)
    session.rollback()
    if order.status is not S.AWAITING_PAYMENT:
        if order.status is S.PENDING:
            raise ShopEaseError(409, "REQUEST_IN_PROGRESS", "The order is still being placed; try again shortly.")
        # Cancelling a paid order needs a refund first (not implemented: docs/order_workflow.md §6).
        raise invalid_transition(order.status, S.CANCELLED)
    if order.payment_status in (PaymentStatus.PROCESSING, PaymentStatus.SUCCEEDED):
        raise ShopEaseError(409, "PAYMENT_IN_PROGRESS",
                            "A payment for this order is being processed; it can't be cancelled now.")

    try:
        response = clients.release(order.id, Deadline.after(4.0))
    except DependencyError as exc:
        raise dependency_error(exc, placed_message="Inventory is unavailable; the order was not cancelled. "
                                                   "Please retry.") from exc
    if response.status_code == 409:  # stock already confirmed: a payment succeeded meanwhile
        raise ShopEaseError(409, "PAYMENT_IN_PROGRESS", "The order was paid meanwhile; it can't be cancelled.")
    if response.status_code != 200:
        raise ShopEaseError(503, "DEPENDENCY_UNAVAILABLE", "Inventory is unavailable; the order was not cancelled.")

    locked = _load(session, order.id, lock=True)
    reason = "CUSTOMER_CANCELLED" if locked.user_id == user.user_id else "ADMIN_CANCELLED"
    transition(session, locked, S.CANCELLED, str(user.user_id), reason)
    session.commit()
    return locked


def set_fulfilment_status(session: Session, order_id: uuid.UUID, target: OrderStatus, admin: Principal) -> Order:
    order = _load(session, order_id, lock=True)
    if order is None:
        raise order_not_found(order_id)
    transition(session, order, target, str(admin.user_id), "fulfilment")
    session.commit()
    return order


# --- payment_service integration (ADR-13) -------------------------------------------------------


def is_payable(order: Order) -> bool:
    return (
        order.status is S.AWAITING_PAYMENT
        and order.payment_due_by is not None
        and order.payment_due_by > utcnow()
        and order.payment_status is not PaymentStatus.SUCCEEDED
    )


def payable_view(session: Session, order_id: uuid.UUID) -> PayableRead:
    order = _load(session, order_id)
    if order is None:
        raise order_not_found(order_id)
    return PayableRead(
        order_id=order.id, user_id=order.user_id, status=order.status, payment_status=order.payment_status,
        payable=is_payable(order), amount=order.total_amount, currency=order.currency,
        payment_due_by=order.payment_due_by,
    )


def apply_payment_result(
    session: Session, clients: ServiceClients, order_id: uuid.UUID, result: PaymentResult, actor: str
) -> Order:
    """Idempotent. A 409 ORDER_NOT_FULFILLABLE tells payment_service to refund."""
    order = _load(session, order_id)
    session.rollback()
    if order is None:
        raise order_not_found(order_id)

    if result.outcome == "SUCCEEDED":
        return _apply_success(session, clients, order, result, actor)

    locked = _load(session, order_id, lock=True)
    if result.outcome in ("FAILED", "PROCESSING"):
        # Declined or unknown: the order keeps its reservation and stays AWAITING_PAYMENT.
        if locked.status is S.AWAITING_PAYMENT and locked.payment_status is not PaymentStatus.SUCCEEDED:
            locked.payment_status = PaymentStatus(result.outcome)
            locked.payment_id = result.payment_id
    elif result.outcome == "REFUNDED":
        if locked.payment_id == result.payment_id or locked.payment_id is None:
            locked.payment_status = PaymentStatus.REFUNDED
            if locked.status is S.PAID:
                # Paid stock is not returned automatically yet (docs/order_workflow.md §6).
                transition(session, locked, S.CANCELLED, actor, "REFUNDED")
    session.commit()
    logger.info("payment result applied", extra={"order_id": str(order_id), "outcome": result.outcome})
    return locked


def _apply_success(
    session: Session, clients: ServiceClients, order: Order, result: PaymentResult, actor: str
) -> Order:
    if order.status in (S.PAID, S.SHIPPED, S.DELIVERED):
        if order.payment_id == result.payment_id:
            return order  # repeated report
        raise ShopEaseError(409, "ORDER_ALREADY_PAID", "The order was already paid by another payment; refund this one.")
    if order.status is not S.AWAITING_PAYMENT:
        _record_unfulfillable(session, order.id, result)
        raise ShopEaseError(409, "ORDER_NOT_FULFILLABLE", "The order is no longer payable; refund this payment.")

    try:
        response = clients.confirm(order.id, Deadline.after(3.5))
    except DependencyError as exc:
        # Unknown whether stock was deducted: payment_service retries later (confirm is idempotent).
        raise dependency_error(exc, placed_message="Inventory is unavailable; report the payment again later.") from exc

    if response.status_code == 200:
        locked = _load(session, order.id, lock=True)
        if locked.status is S.AWAITING_PAYMENT:
            transition(session, locked, S.PAID, actor, "payment succeeded")
        locked.payment_id = result.payment_id
        locked.payment_status = PaymentStatus.SUCCEEDED
        locked.release_pending = False
        session.commit()
        logger.info("order paid", extra={"order_id": str(order.id)})
        return locked
    if response.status_code in (404, 409):
        # Reservation expired or released: the stock is gone. Cancel; payment_service refunds.
        locked = _load(session, order.id, lock=True)
        if locked.status is S.AWAITING_PAYMENT:
            transition(session, locked, S.CANCELLED, actor, "RESERVATION_EXPIRED")
        session.commit()
        _record_unfulfillable(session, order.id, result)
        raise ShopEaseError(409, "ORDER_NOT_FULFILLABLE", "The reserved stock expired; refund this payment.")
    raise ShopEaseError(503, "DEPENDENCY_UNAVAILABLE", "Inventory returned an unexpected answer; retry later.")


def _record_unfulfillable(session: Session, order_id: uuid.UUID, result: PaymentResult) -> None:
    locked = _load(session, order_id, lock=True)
    locked.payment_id = result.payment_id
    locked.payment_status = PaymentStatus.SUCCEEDED  # charged; a refund is expected next
    session.commit()


# --- Recovery job ---------------------------------------------------------------------------


def _release_and_cancel(
    session: Session, clients: ServiceClients, order_id: uuid.UUID, expected: OrderStatus, reason: str
) -> bool:
    try:
        response = clients.release(order_id, Deadline.after(4.0))
    except DependencyError:
        return False
    if response.status_code == 409:
        return False  # confirmed meanwhile: a payment result is on its way
    if response.status_code != 200:
        return False
    locked = _load(session, order_id, lock=True)
    if locked.status is expected:
        transition(session, locked, S.CANCELLED, "system:recovery", reason)
        locked.release_pending = False
    session.commit()
    return True


def recover(session: Session, clients: ServiceClients, settings: Settings, batch: int = 50) -> dict[str, int]:
    """Expire unpaid orders, clean up abandoned PENDING orders, retry pending stock releases."""
    now = utcnow()
    expired = session.scalars(
        select(Order.id).where(Order.status == S.AWAITING_PAYMENT, Order.payment_due_by <= now).limit(batch)
    ).all()
    stuck = session.scalars(
        select(Order.id).where(
            Order.status == S.PENDING, Order.created_at <= now - timedelta(seconds=settings.stuck_pending_seconds)
        ).limit(batch)
    ).all()
    pending_release = session.scalars(select(Order.id).where(Order.release_pending.is_(True)).limit(batch)).all()
    session.rollback()

    counts = {"expired": 0, "stuck": 0, "released": 0}
    for order_id in expired:
        counts["expired"] += _release_and_cancel(session, clients, order_id, S.AWAITING_PAYMENT, "PAYMENT_TIMEOUT")
    for order_id in stuck:
        counts["stuck"] += _release_and_cancel(session, clients, order_id, S.PENDING, "STUCK_PENDING")
    for order_id in pending_release:
        try:
            response = clients.release(order_id, Deadline.after(4.0))
        except DependencyError:
            continue
        if response.status_code in (200, 409):  # released, or confirmed (nothing left to release)
            locked = _load(session, order_id, lock=True)
            locked.release_pending = False
            session.commit()
            counts["released"] += 1
    if any(counts.values()):
        logger.info("order recovery", extra=counts)
    return counts
