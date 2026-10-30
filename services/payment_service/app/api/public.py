"""Public /api/payments routes (rest_api_notes.md §3.6). Reached through the gateway.

Customers pay for and read only their own orders' payments (the owner comes from
order_service's payable view and must match the token). Admins read all and refund.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app import payments
from app.dependencies import DbSession
from app.schemas import Page, PaymentCreate, PaymentRead, PaymentSummary, RefundCreate, RefundRead
from shopease_shared import ShopEaseError
from shopease_shared.security import AdminUser, CurrentUser

router = APIRouter(prefix="/api/payments", tags=["payments"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$",
           description="Unique per intended payment; reuse it on every retry of that payment"),
]


def get_ctx(request: Request) -> payments.Ctx:
    return request.app.state.payment_ctx


Ctx = Annotated[payments.Ctx, Depends(get_ctx)]


@router.post(
    "",
    status_code=201,
    response_model=PaymentRead,
    summary="Pay for an order (requires Idempotency-Key)",
    responses={202: {"model": PaymentRead, "description": "Outcome not known yet (PROCESSING); poll GET /api/payments/{id}"}},
)
def create_payment(
    body: PaymentCreate, user: CurrentUser, key: IdempotencyKey, session: DbSession, ctx: Ctx, response: Response
) -> PaymentRead:
    payment, status = payments.create_payment(session, ctx, user, body, key)
    response.status_code = status
    response.headers["Location"] = f"/api/payments/{payment.id}"
    return payments.to_read(payment)


@router.get("", response_model=Page[PaymentSummary], summary="List payments (own; admins: all), optionally for one order")
def list_payments(
    user: CurrentUser,
    session: DbSession,
    order_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PaymentSummary]:
    items, total = payments.list_payments(session, user, order_id, limit, offset)
    return Page[PaymentSummary](
        items=[PaymentSummary(payment_id=p.id, order_id=p.order_id, status=p.status, amount=p.amount,
                              currency=p.currency, created_at=p.created_at) for p in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{payment_id}", response_model=PaymentRead, summary="Payment status and history")
def get_payment(payment_id: UUID, user: CurrentUser, session: DbSession) -> PaymentRead:
    return payments.to_read(payments.get_visible_payment(session, payment_id, user))


@router.post(
    "/{payment_id}/refunds",
    status_code=201,
    response_model=RefundRead,
    summary="Refund a payment, fully or partly (admin; requires Idempotency-Key)",
)
def create_refund(
    payment_id: UUID, body: RefundCreate, admin: AdminUser, key: IdempotencyKey, session: DbSession, ctx: Ctx,
    response: Response,
) -> RefundRead:
    if payments._load(session, payment_id) is None:
        raise payments.payment_not_found(payment_id)
    session.rollback()
    refund = payments.refund_payment(session, ctx, payment_id, body.amount, reason=body.reason,
                                     actor=str(admin.user_id), idempotency_key=f"admin-{key}")
    payments.report_result(session, ctx, payment_id)
    if refund.status.value != "SUCCEEDED":
        response.status_code = 202
    return RefundRead.model_validate(refund)


@router.post("/webhooks/{provider}", summary="Provider webhook (not used by the mock provider)")
def provider_webhook(provider: str) -> None:
    # A real provider adapter would verify the provider's signature here before trusting
    # any status update. The mock provider sends no webhooks; reconciliation covers it.
    raise ShopEaseError(501, "WEBHOOKS_NOT_SUPPORTED", "The configured payment provider does not send webhooks.")
