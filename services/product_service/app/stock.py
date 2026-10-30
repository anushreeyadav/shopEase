"""Stock changes: admin adjustments and checkout reservations, safe under concurrency.

How overselling is prevented:
1. Every change is one database transaction.
2. The inventory rows involved are locked with SELECT ... FOR UPDATE, always in product_id
   order, so two multi-item checkouts can't deadlock each other by locking in opposite order.
3. Availability (on_hand - reserved) is checked while holding the lock, so no other
   transaction can change it between the check and the update.
4. CHECK constraints (on_hand >= 0, reserved >= 0, reserved <= on_hand) reject anything the
   code missed, and the `version` column turns a lost update into an error.
5. MySQL deadlocks or lock-wait timeouts roll back and are retried a bounded number of times.
6. Sessions run at READ COMMITTED on MySQL (app/db.py), which avoids gap locks; every stock
   decision reads locked rows, which always see the latest committed values.

Reservations are keyed by order_id (unique per order and product), so every operation can be
retried safely by order_service: reserve replays, confirm and release are idempotent.
Every change appends an inventory_movements row: what changed, the levels after, who, why.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.errors import conflict, product_not_found, reservation_not_found
from app.models import (
    Inventory,
    InventoryMovement,
    MovementReason,
    Product,
    ProductStatus,
    ReservationStatus,
    StockReservation,
)
from app.models.base import utcnow
from app.schemas import (
    PriceCheckItem,
    PriceCheckResponse,
    ReservationItemIn,
    ReservationItemOut,
    ReservationResponse,
)
from shopease_shared import ShopEaseError

logger = logging.getLogger(__name__)
T = TypeVar("T")

_RETRYABLE_MYSQL_ERRORS = {1213, 1205}  # deadlock, lock wait timeout
MAX_ATTEMPTS = 3


def run_with_retry(session: Session, operation: Callable[[], T]) -> T:
    """Run a whole transaction again after a deadlock or lock timeout (bounded)."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return operation()
        except OperationalError as exc:
            session.rollback()
            code = getattr(exc.orig, "args", [None])[0]
            if code not in _RETRYABLE_MYSQL_ERRORS:
                raise
            logger.warning("stock transaction retried", extra={"mysql_error": code, "attempt": attempt})
    raise ShopEaseError(503, "SERVICE_BUSY", "Stock is busy; retry shortly.", headers={"Retry-After": "1"})


def record_movement(
    session: Session,
    inventory: Inventory,
    reason: MovementReason,
    quantity_change: int,
    reserved_change: int,
    actor: str,
    reference_id: uuid.UUID | None = None,
    note: str | None = None,
) -> None:
    """Append the audit row. Call after changing `inventory`, so the *_after levels are current."""
    session.add(
        InventoryMovement(
            product_id=inventory.product_id,
            reason=reason,
            quantity_change=quantity_change,
            reserved_change=reserved_change,
            on_hand_after=inventory.quantity_on_hand,
            reserved_after=inventory.quantity_reserved,
            reference_id=reference_id,
            actor=actor,
            note=note,
        )
    )


def lock_inventory(session: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, Inventory]:
    rows = session.scalars(
        select(Inventory)
        .where(Inventory.product_id.in_(product_ids))
        .order_by(Inventory.product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return {row.product_id: row for row in rows}


# --- Admin adjustments -------------------------------------------------------------------


def adjust_stock(
    session: Session, product_id: uuid.UUID, change: int, reason: MovementReason, actor: str, note: str | None
) -> Inventory:
    def operation() -> Inventory:
        if session.get(Product, product_id) is None:
            raise product_not_found(product_id)
        inventory = lock_inventory(session, [product_id])[product_id]
        new_on_hand = inventory.quantity_on_hand + change
        if new_on_hand < inventory.quantity_reserved:
            raise conflict(
                "INSUFFICIENT_STOCK",
                "The adjustment would leave less stock than is reserved for open orders.",
                [{
                    "field": "body.quantity_change",
                    "issue": f"on hand {inventory.quantity_on_hand}, reserved {inventory.quantity_reserved}",
                }],
            )
        inventory.quantity_on_hand = new_on_hand
        record_movement(session, inventory, reason, change, 0, actor, note=note)
        session.commit()
        return inventory

    return run_with_retry(session, operation)


# --- Availability ----------------------------------------------------------------------


def price_check(session: Session, product_ids: list[uuid.UUID]) -> PriceCheckResponse:
    """Current prices and availability (no locks: a snapshot for building an order)."""
    rows = session.execute(
        select(Product, Inventory).join(Inventory, Inventory.product_id == Product.id).where(Product.id.in_(product_ids))
    ).all()
    items = []
    for product, inventory in rows:
        available = inventory.quantity_on_hand - inventory.quantity_reserved
        items.append(
            PriceCheckItem(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                price=product.price,
                currency=product.currency,
                status=product.status,
                available_quantity=available,
                orderable=product.status is ProductStatus.ACTIVE and available > 0,
            )
        )
    found = {item.product_id for item in items}
    return PriceCheckResponse(items=items, missing=[pid for pid in product_ids if pid not in found])


# --- Reservations ----------------------------------------------------------------------


def _order_reservations(session: Session, order_id: uuid.UUID) -> list[StockReservation]:
    return list(
        session.scalars(
            select(StockReservation)
            .where(StockReservation.order_id == order_id)
            .order_by(StockReservation.product_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )


def _response(order_id: uuid.UUID, rows: list[StockReservation]) -> ReservationResponse:
    statuses = {row.status for row in rows}
    return ReservationResponse(
        order_id=order_id,
        status=statuses.pop() if len(statuses) == 1 else ReservationStatus.RESERVED,
        expires_at=min(row.expires_at for row in rows),
        items=[ReservationItemOut(product_id=r.product_id, quantity=r.quantity, status=r.status) for r in rows],
    )


def reserve(
    session: Session,
    order_id: uuid.UUID,
    items: list[ReservationItemIn],
    ttl: timedelta,
    actor: str,
) -> tuple[ReservationResponse, bool]:
    """All-or-nothing reservation. Returns (reservation, created). A replay returns created=False."""
    requested = {item.product_id: item.quantity for item in items}

    def operation() -> tuple[ReservationResponse, bool]:
        # Plain read, not FOR UPDATE: locking a not-yet-existing order_id takes a gap lock that
        # blocks *other* orders' inserts and deadlocks busy checkouts. Two requests for the same
        # order are settled by the unique (order_id, product_id) key: the loser replays.
        existing = list(
            session.scalars(
                select(StockReservation)
                .where(StockReservation.order_id == order_id)
                .order_by(StockReservation.product_id)
            ).all()
        )
        if existing:
            if {r.product_id: r.quantity for r in existing} != requested:
                raise conflict(
                    "RESERVATION_CONFLICT", "This order already has a different stock reservation."
                )
            response = _response(order_id, existing)
            session.rollback()
            return response, False

        products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(requested))).all()}
        missing = [pid for pid in requested if pid not in products]
        if missing:
            raise ShopEaseError(
                404,
                "PRODUCT_NOT_FOUND",
                "Some products do not exist.",
                [{"field": "body.items", "issue": f"unknown product {pid}"} for pid in missing],
            )
        archived = [pid for pid, p in products.items() if p.status is not ProductStatus.ACTIVE]
        if archived:
            raise conflict(
                "PRODUCT_UNAVAILABLE",
                "Some products are no longer sold.",
                [{"field": "body.items", "issue": f"product {pid} is archived"} for pid in archived],
            )

        inventories = lock_inventory(session, sorted(requested))
        shortages = []
        for product_id, quantity in requested.items():
            inventory = inventories[product_id]
            available = inventory.quantity_on_hand - inventory.quantity_reserved
            if quantity > available:
                shortages.append(
                    {"field": "body.items", "issue": f"product {product_id}: requested {quantity}, available {available}"}
                )
        if shortages:
            raise conflict("OUT_OF_STOCK", "Not enough stock for some items; nothing was reserved.", shortages)

        expires_at = utcnow() + ttl
        rows = []
        for product_id in sorted(requested):
            quantity = requested[product_id]
            inventory = inventories[product_id]
            inventory.quantity_reserved += quantity
            rows.append(
                StockReservation(order_id=order_id, product_id=product_id, quantity=quantity, expires_at=expires_at)
            )
            record_movement(session, inventory, MovementReason.RESERVE, 0, quantity, actor, reference_id=order_id)
        session.add_all(rows)
        session.commit()
        logger.info("stock reserved", extra={"order_id": str(order_id), "items": len(rows)})
        return _response(order_id, rows), True

    try:
        return run_with_retry(session, operation)
    except IntegrityError:
        # A concurrent request for the same order won the race: replay its result.
        session.rollback()
        return run_with_retry(session, operation)


def _return_reserved_stock(
    session: Session,
    rows: list[StockReservation],
    new_status: ReservationStatus,
    actor: str,
    note: str | None,
) -> int:
    active = [r for r in rows if r.status is ReservationStatus.RESERVED]
    inventories = lock_inventory(session, sorted({r.product_id for r in active}))
    for row in active:
        inventory = inventories[row.product_id]
        inventory.quantity_reserved -= row.quantity
        row.status = new_status
        record_movement(
            session, inventory, MovementReason.RELEASE, 0, -row.quantity, actor, reference_id=row.order_id, note=note
        )
    return len(active)


def confirm(session: Session, order_id: uuid.UUID, actor: str) -> ReservationResponse:
    """Payment succeeded: deduct the reserved stock. Idempotent for an already confirmed order."""

    def operation() -> ReservationResponse:
        rows = _order_reservations(session, order_id)
        if not rows:
            raise reservation_not_found(order_id)
        statuses = {r.status for r in rows}
        if statuses == {ReservationStatus.CONFIRMED}:
            response = _response(order_id, rows)
            session.rollback()
            return response
        if statuses & {ReservationStatus.RELEASED, ReservationStatus.EXPIRED}:
            raise conflict("RESERVATION_EXPIRED", "The reservation was released or has expired.")
        if any(r.expires_at <= utcnow() for r in rows if r.status is ReservationStatus.RESERVED):
            # Expired but not yet swept: return the stock now, then refuse (payment gets refunded).
            _return_reserved_stock(session, rows, ReservationStatus.EXPIRED, actor, note="expired at confirm")
            session.commit()
            raise conflict("RESERVATION_EXPIRED", "The reservation has expired.")

        inventories = lock_inventory(session, sorted({r.product_id for r in rows}))
        for row in rows:
            inventory = inventories[row.product_id]
            inventory.quantity_on_hand -= row.quantity
            inventory.quantity_reserved -= row.quantity
            row.status = ReservationStatus.CONFIRMED
            record_movement(
                session, inventory, MovementReason.CONFIRM, -row.quantity, -row.quantity, actor, reference_id=order_id
            )
        session.commit()
        logger.info("stock confirmed", extra={"order_id": str(order_id)})
        return _response(order_id, rows)

    return run_with_retry(session, operation)


def release(session: Session, order_id: uuid.UUID, actor: str) -> int:
    """Order cancelled or the reserve call timed out: return the stock. Idempotent.

    Returns how many reservation lines were released (0 if there was nothing to release).
    """

    def operation() -> int:
        rows = _order_reservations(session, order_id)
        if any(r.status is ReservationStatus.CONFIRMED for r in rows):
            raise conflict(
                "RESERVATION_ALREADY_CONFIRMED", "The stock was already deducted for this order; it can't be released."
            )
        released = _return_reserved_stock(session, rows, ReservationStatus.RELEASED, actor, note=None)
        session.commit()
        if released:
            logger.info("stock released", extra={"order_id": str(order_id), "items": released})
        return released

    return run_with_retry(session, operation)


def expire_due(session: Session, batch_size: int = 100) -> int:
    """Background job: release reservations past expires_at. SKIP LOCKED leaves busy rows for later."""

    def operation() -> int:
        rows = list(
            session.scalars(
                select(StockReservation)
                .where(StockReservation.status == ReservationStatus.RESERVED, StockReservation.expires_at <= utcnow())
                .order_by(StockReservation.expires_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()
        )
        expired = _return_reserved_stock(session, rows, ReservationStatus.EXPIRED, "system:expiry", note="expired")
        session.commit()
        if expired:
            logger.info("expired reservations released", extra={"count": expired})
        return expired

    return run_with_retry(session, operation)
