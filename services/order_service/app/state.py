"""Order status machine (docs/order_workflow.md §3). Every change goes through `transition`."""

from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, OrderStatusHistory
from shopease_shared import ShopEaseError

S = OrderStatus

ALLOWED: dict[OrderStatus | None, frozenset[OrderStatus]] = {
    None: frozenset({S.PENDING}),
    S.PENDING: frozenset({S.AWAITING_PAYMENT, S.CANCELLED}),
    S.AWAITING_PAYMENT: frozenset({S.PAID, S.CANCELLED}),
    S.PAID: frozenset({S.SHIPPED, S.CANCELLED}),  # PAID -> CANCELLED only after a refund
    S.SHIPPED: frozenset({S.DELIVERED}),
    S.DELIVERED: frozenset(),
    S.CANCELLED: frozenset(),
}


def can_transition(current: OrderStatus | None, target: OrderStatus) -> bool:
    return target in ALLOWED[current]


def invalid_transition(current: OrderStatus | None, target: OrderStatus) -> ShopEaseError:
    return ShopEaseError(
        409,
        "INVALID_STATUS_TRANSITION",
        f"An order in status {current.value if current else 'none'} can't move to {target.value}.",
    )


def transition(
    session: Session, order: Order, target: OrderStatus, changed_by: str, reason: str | None = None
) -> None:
    """Change the status and append the audit row. The caller commits (one local transaction)."""
    current = None if order.status is None and not order.status_history else order.status
    if not can_transition(current, target):
        raise invalid_transition(current, target)
    order.status_history.append(
        OrderStatusHistory(from_status=current, to_status=target, changed_by=changed_by, reason=reason)
    )
    order.status = target
    if target is S.CANCELLED and reason:
        order.cancel_reason = reason
