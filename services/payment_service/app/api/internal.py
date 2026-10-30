"""Internal /internal/payments routes. Never routed by the gateway.

Reconciliation normally runs in the background job; this endpoint lets an operator tool
trigger it for one payment (service token with scope `payments:reconcile`).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app import payments
from app.api.public import Ctx
from app.dependencies import DbSession
from app.schemas import PaymentRead
from shopease_shared.security import Principal, require_scope

router = APIRouter(prefix="/internal/payments", tags=["internal"])


@router.post(
    "/{payment_id}/reconcile",
    response_model=PaymentRead,
    summary="Ask the provider for the outcome of an unresolved payment (scope payments:reconcile)",
)
def reconcile(
    payment_id: UUID,
    service: Annotated[Principal, Depends(require_scope("payments:reconcile"))],
    session: DbSession,
    ctx: Ctx,
    include_manual_review: bool = False,
) -> PaymentRead:
    payment = payments.reconcile(session, ctx, payment_id, force=include_manual_review)
    return payments.to_read(payments._load(session, payment.id))
