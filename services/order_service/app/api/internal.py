"""Internal /internal/orders routes for payment_service (rest_api_notes.md Part 4, ADR-13).

payment_service reads the authoritative amount here and reports each payment outcome.
Never routed by the gateway; each route requires a service token with the listed scope.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app import orders
from app.api.public import Clients
from app.dependencies import DbSession
from app.schemas import PayableRead, PaymentResult, PaymentResultRead
from shopease_shared.security import Principal, require_scope

router = APIRouter(prefix="/internal/orders", tags=["internal"])


@router.get("/{order_id}/payable", response_model=PayableRead, summary="Payable amount and status (scope orders:read)")
def payable(
    order_id: UUID, service: Annotated[Principal, Depends(require_scope("orders:read"))], session: DbSession
) -> PayableRead:
    return orders.payable_view(session, order_id)


@router.post(
    "/{order_id}/payment-result",
    response_model=PaymentResultRead,
    summary="Report a payment outcome; idempotent (scope orders:payment)",
    responses={409: {"description": "ORDER_NOT_FULFILLABLE or ORDER_ALREADY_PAID: refund this payment"}},
)
def payment_result(
    order_id: UUID,
    body: PaymentResult,
    service: Annotated[Principal, Depends(require_scope("orders:payment"))],
    session: DbSession,
    clients: Clients,
) -> PaymentResultRead:
    order = orders.apply_payment_result(session, clients, order_id, body, actor=service.subject)
    return PaymentResultRead(order_id=order.id, status=order.status, payment_status=order.payment_status)
