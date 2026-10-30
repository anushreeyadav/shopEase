"""Payment rules (docs/payment_processing.md).

Safety rules enforced here:
1. A payment is SUCCEEDED only after the provider returned an accepted result whose amount,
   currency and (unique) reference check out. Anything inconsistent stays PROCESSING and is
   flagged for manual review.
2. A timeout after the request may have been sent is an unknown outcome: PROCESSING, then
   reconciled with `get_status`. A charge is never sent again for the same payment, and a
   new payment for the order is blocked while one is active (`active_order_id` is unique).
3. No database transaction stays open across a provider or order_service call.
4. Tokens and card data are never stored or logged; only brand, last four and references.
"""

import hashlib
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.clients import DependencyError, ServiceClients
from app.config import Settings
from app.models import Payment, PaymentStatus, PaymentStatusHistory, Refund, RefundStatus, StatusSource
from app.models.base import utcnow
from app.providers.base import (
    ChargeOutcome,
    ChargeResult,
    InvalidPaymentMethod,
    PaymentProvider,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.schemas import (
    PaymentCreate,
    PaymentMethodRead,
    PaymentRead,
    RefundRead,
    StatusEventRead,
)
from shopease_shared import ShopEaseError
from shopease_shared.security import Principal

logger = logging.getLogger(__name__)
P = PaymentStatus

ALLOWED = {
    None: {P.INITIATED},
    P.INITIATED: {P.SUCCEEDED, P.FAILED, P.PROCESSING},
    P.PROCESSING: {P.SUCCEEDED, P.FAILED},
    P.SUCCEEDED: {P.REFUNDED},
    P.FAILED: set(),
    P.REFUNDED: set(),
}
ACTIVE = {P.INITIATED, P.PROCESSING, P.SUCCEEDED}

# failure_reason values that decide how a replayed Idempotency-Key is answered.
PROVIDER_UNAVAILABLE = "provider_unavailable"
ORDER_NOT_FULFILLABLE = "order_not_fulfillable"


class Ctx:
    """What the payment rules need besides the session."""

    def __init__(self, settings: Settings, clients: ServiceClients, provider: PaymentProvider) -> None:
        self.settings, self.clients, self.provider = settings, clients, provider


# --- Errors and reads ------------------------------------------------------------------------


def payment_not_found(payment_id: uuid.UUID) -> ShopEaseError:
    return ShopEaseError(404, "PAYMENT_NOT_FOUND", f"Payment {payment_id} was not found.")


def _load(session: Session, payment_id: uuid.UUID, lock: bool = False) -> Payment | None:
    query = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.refunds), selectinload(Payment.status_history))
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return session.scalars(query).one_or_none()


def get_visible_payment(session: Session, payment_id: uuid.UUID, user: Principal) -> Payment:
    payment = _load(session, payment_id)
    if payment is None or (payment.user_id != user.user_id and not user.is_admin):
        raise payment_not_found(payment_id)
    return payment


def to_read(payment: Payment) -> PaymentRead:
    method = (
        PaymentMethodRead(brand=payment.card_brand, last4=payment.card_last4)
        if payment.card_brand or payment.card_last4
        else None
    )
    return PaymentRead(
        payment_id=payment.id,
        order_id=payment.order_id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        provider=payment.provider,
        payment_method=method,
        provider_reference=payment.provider_txn_ref,
        failure_reason=payment.failure_reason,
        requires_review=payment.needs_manual_review,
        refunds=[RefundRead.model_validate(r) for r in sorted(payment.refunds, key=lambda r: r.created_at)],
        status_history=[
            StatusEventRead.model_validate(h) for h in sorted(payment.status_history, key=lambda h: (h.created_at, h.id))
        ],
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


def list_payments(session: Session, user: Principal, order_id: uuid.UUID | None, limit: int, offset: int):
    query = select(Payment)
    if not user.is_admin:
        query = query.where(Payment.user_id == user.user_id)
    if order_id is not None:
        query = query.where(Payment.order_id == order_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Payment.created_at.desc(), Payment.id).limit(limit).offset(offset)).all()
    return list(items), total


# --- State changes (each caller holds the row lock and commits) --------------------------------


def _set_status(session: Session, payment: Payment, target: PaymentStatus, source: StatusSource) -> None:
    current = None if payment.status is None and not payment.status_history else payment.status
    if target not in ALLOWED[current]:
        raise ShopEaseError(409, "INVALID_STATUS_TRANSITION", f"Payment can't move from {current} to {target}.")
    payment.status_history.append(PaymentStatusHistory(from_status=current, to_status=target, source=source))
    payment.status = target
    if target not in ACTIVE:
        payment.active_order_id = None  # frees the order for a new attempt (FAILED) or ends it (REFUNDED)
    # Every new status must reach order_service.
    payment.result_reported_at = None
    payment.report_attempts = 0
    payment.next_report_at = utcnow()


def _schedule_reconcile(payment: Payment, settings: Settings) -> None:
    schedule = settings.reconcile_schedule_seconds
    if payment.reconcile_attempts >= len(schedule):
        payment.needs_manual_review = True
        payment.next_reconcile_at = None
        logger.error("payment needs manual review", extra={"payment_id": str(payment.id), "reason": "unresolved"})
        return
    payment.next_reconcile_at = utcnow() + timedelta(seconds=schedule[payment.reconcile_attempts])


def _flag_for_review(session: Session, payment: Payment, reason: str, source: StatusSource) -> None:
    """Money may have moved but the answer is inconsistent: never call it SUCCEEDED."""
    if payment.status is P.INITIATED:
        _set_status(session, payment, P.PROCESSING, source)
    payment.needs_manual_review = True
    payment.next_reconcile_at = None
    payment.failure_reason = reason
    logger.error("payment needs manual review", extra={"payment_id": str(payment.id), "reason": reason})


def apply_charge_result(
    session: Session, settings: Settings, payment_id: uuid.UUID, result: ChargeResult, source: StatusSource
) -> Payment:
    payment = _load(session, payment_id, lock=True)
    if payment.status not in (P.INITIATED, P.PROCESSING):
        session.commit()
        return payment  # already final (e.g. a duplicate reconciliation)

    if result.outcome is ChargeOutcome.DECLINED:
        _set_status(session, payment, P.FAILED, source)
        payment.failure_reason = result.decline_code or "declined"
        payment.card_brand, payment.card_last4 = result.card_brand, result.card_last4
    elif result.outcome is ChargeOutcome.PENDING:
        if payment.status is P.INITIATED:
            _set_status(session, payment, P.PROCESSING, source)
        payment.reconcile_attempts += 1 if source is StatusSource.RECONCILIATION else 0
        _schedule_reconcile(payment, settings)
    elif result.amount != payment.amount or result.currency != payment.currency:
        _flag_for_review(session, payment, "provider_amount_mismatch", source)
    else:
        _set_status(session, payment, P.SUCCEEDED, source)
        payment.provider_txn_ref = result.provider_reference
        payment.card_brand, payment.card_last4 = result.card_brand, result.card_last4
        payment.failure_reason = None
        payment.next_reconcile_at = None
        try:
            session.commit()
        except IntegrityError:
            # The provider reference is already recorded for another payment: inconsistent.
            session.rollback()
            payment = _load(session, payment_id, lock=True)
            _flag_for_review(session, payment, "duplicate_provider_reference", source)
            session.commit()
            return payment
        logger.info("payment succeeded", extra={"payment_id": str(payment.id), "order_id": str(payment.order_id)})
        return payment
    session.commit()
    return payment


def _mark_unknown(session: Session, settings: Settings, payment_id: uuid.UUID, source: StatusSource) -> Payment:
    payment = _load(session, payment_id, lock=True)
    if payment.status is P.INITIATED:
        _set_status(session, payment, P.PROCESSING, source)
    if source is StatusSource.RECONCILIATION:
        payment.reconcile_attempts += 1
    _schedule_reconcile(payment, settings)
    session.commit()
    logger.warning("payment outcome unknown; reconciliation scheduled", extra={"payment_id": str(payment_id)})
    return payment


# --- Creating a payment ---------------------------------------------------------------------------


def _fingerprint(body: PaymentCreate) -> str:
    canonical = {
        "order_id": str(body.order_id),
        "token": hashlib.sha256(body.payment_method_token.encode()).hexdigest(),
        "expected_amount": str(body.expected_amount) if body.expected_amount is not None else None,
        "currency": body.currency,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def _replay(payment: Payment, user: Principal, fingerprint: str) -> tuple[Payment, int]:
    if payment.user_id != user.user_id or payment.request_fingerprint != fingerprint:
        raise ShopEaseError(409, "IDEMPOTENCY_KEY_REUSED",
                            "This Idempotency-Key was already used with a different request.")
    return payment, _answer(payment)


def _answer(payment: Payment) -> int:
    """HTTP status for a payment's current state (raises for failures)."""
    if payment.status is P.FAILED:
        if payment.failure_reason == PROVIDER_UNAVAILABLE:
            raise ShopEaseError(503, "PAYMENT_PROVIDER_UNAVAILABLE",
                                "The payment provider is unavailable; nothing was charged. "
                                "Retry with a new Idempotency-Key.", headers={"Retry-After": "5"})
        raise ShopEaseError(422, "PAYMENT_DECLINED", "The payment was declined by the provider.")
    if payment.status is P.REFUNDED and payment.failure_reason == ORDER_NOT_FULFILLABLE:
        raise ShopEaseError(409, "ORDER_NOT_FULFILLABLE",
                            "The order could no longer be fulfilled, so the payment was refunded.")
    if payment.status in (P.INITIATED, P.PROCESSING):
        return 202
    return 201


def _order_error(exc: DependencyError) -> ShopEaseError:
    code, status = ("DEPENDENCY_TIMEOUT", 504) if exc.kind == "timeout" else ("DEPENDENCY_UNAVAILABLE", 503)
    return ShopEaseError(status, code, "Orders are temporarily unavailable; nothing was charged. Please retry.",
                         headers={"Retry-After": "2"})


def create_payment(
    session: Session, ctx: Ctx, user: Principal, body: PaymentCreate, idempotency_key: str
) -> tuple[Payment, int]:
    """Returns (payment, HTTP status). Raises for declines, conflicts and dependency failures."""
    fingerprint = _fingerprint(body)
    existing = session.scalars(select(Payment).where(Payment.idempotency_key == idempotency_key)).one_or_none()
    session.rollback()
    if existing is not None:
        return _replay(_load(session, existing.id), user, fingerprint)

    try:
        ctx.provider.validate_token(body.payment_method_token)
    except InvalidPaymentMethod as exc:
        raise ShopEaseError(422, "INVALID_PAYMENT_METHOD", "The payment method is not accepted.") from exc

    # The authoritative amount, owner and status come from order_service.
    try:
        response = ctx.clients.payable(body.order_id)
    except DependencyError as exc:
        raise _order_error(exc) from exc
    if response.status_code == 404:
        raise ShopEaseError(404, "ORDER_NOT_FOUND", f"Order {body.order_id} was not found.")
    if response.status_code != 200:
        raise _order_error(DependencyError("order_service", "unavailable", str(response.status_code)))
    order = response.json()
    if order["user_id"] != str(user.user_id):
        raise ShopEaseError(404, "ORDER_NOT_FOUND", f"Order {body.order_id} was not found.")  # no ID probing
    if not order["payable"]:
        raise ShopEaseError(409, "ORDER_NOT_PAYABLE", f"Order {body.order_id} can't be paid (status {order['status']}).")
    amount, currency = Decimal(order["amount"]), order["currency"]
    if body.expected_amount is not None and body.expected_amount != amount:
        raise ShopEaseError(409, "AMOUNT_MISMATCH", "The order total differs from the expected amount; nothing was charged.",
                            [{"field": "body.expected_amount", "issue": f"order total is {amount} {currency}"}])
    if body.currency is not None and body.currency != currency:
        raise ShopEaseError(409, "CURRENCY_MISMATCH", "The order currency differs; nothing was charged.",
                            [{"field": "body.currency", "issue": f"order currency is {currency}"}])

    # Record the attempt before charging (one short transaction).
    payment = Payment(
        id=uuid.uuid4(), order_id=body.order_id, user_id=user.user_id, amount=amount, currency=currency,
        provider=ctx.provider.name, idempotency_key=idempotency_key, request_fingerprint=fingerprint,
        active_order_id=body.order_id,
    )
    _set_status(session, payment, P.INITIATED, StatusSource.API)
    payment.next_report_at = None  # nothing to report until the provider answers
    session.add(payment)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalars(select(Payment).where(Payment.idempotency_key == idempotency_key)).one_or_none()
        if existing is not None:
            return _replay(_load(session, existing.id), user, fingerprint)
        raise ShopEaseError(409, "PAYMENT_ALREADY_IN_PROGRESS",
                            "This order already has an active payment; wait for its outcome.")

    # Charge (no transaction open). The provider idempotency key is our payment ID.
    try:
        result = ctx.provider.charge(str(payment.id), amount, currency, body.payment_method_token)
    except ProviderUnavailable:
        locked = _load(session, payment.id, lock=True)
        _set_status(session, locked, P.FAILED, StatusSource.API)
        locked.failure_reason = PROVIDER_UNAVAILABLE
        locked.result_reported_at = utcnow()  # nothing happened: order_service needn't know
        session.commit()
        _answer(locked)
    except ProviderTimeout:
        payment = _mark_unknown(session, ctx.settings, payment.id, StatusSource.API)
    except ProviderError:
        payment = _mark_unknown(session, ctx.settings, payment.id, StatusSource.API)
    else:
        payment = apply_charge_result(session, ctx.settings, payment.id, result, StatusSource.API)

    payment = report_result(session, ctx, payment.id)
    return payment, _answer(payment)


# --- Reporting to order_service and automatic refunds -------------------------------------------


def report_result(session: Session, ctx: Ctx, payment_id: uuid.UUID) -> Payment:
    """Tell order_service the current outcome. Failures are retried later by the job."""
    payment = _load(session, payment_id)
    session.rollback()
    if payment.result_reported_at is not None or payment.status is P.INITIATED:
        return payment
    try:
        response = ctx.clients.report_result(payment.order_id, payment.id, payment.status.value, payment.failure_reason)
    except DependencyError as exc:
        return _report_failed(session, ctx.settings, payment_id, exc.kind)

    code = None
    if response.status_code >= 400:
        try:
            code = response.json().get("error", {}).get("code")
        except ValueError:
            code = None
    if response.status_code == 200:
        locked = _load(session, payment_id, lock=True)
        if locked.status is payment.status:
            locked.result_reported_at = utcnow()
            locked.next_report_at = None
        session.commit()
        return locked
    if response.status_code == 409 and code in ("ORDER_NOT_FULFILLABLE", "ORDER_ALREADY_PAID") and payment.status is P.SUCCEEDED:
        # Compensation: the order can't accept this money. Refund it in full, then report that.
        refund_payment(session, ctx, payment_id, None, reason=code.lower(), actor="system:compensation",
                       idempotency_key=f"auto-{payment_id}")
        locked = _load(session, payment_id, lock=True)
        locked.failure_reason = ORDER_NOT_FULFILLABLE
        session.commit()
        return report_result(session, ctx, payment_id)
    logger.error("payment result rejected by order_service",
                 extra={"payment_id": str(payment_id), "status": response.status_code, "code": code})
    return _report_failed(session, ctx.settings, payment_id, f"status_{response.status_code}")


def _report_failed(session: Session, settings: Settings, payment_id: uuid.UUID, why: str) -> Payment:
    locked = _load(session, payment_id, lock=True)
    locked.report_attempts += 1
    if locked.report_attempts >= settings.max_report_attempts:
        locked.next_report_at = None
        locked.needs_manual_review = True
        logger.error("payment result could not be reported", extra={"payment_id": str(payment_id)})
    else:
        locked.next_report_at = utcnow() + timedelta(seconds=min(10 * 2 ** locked.report_attempts, 3600))
    session.commit()
    logger.warning("payment result report failed; will retry", extra={"payment_id": str(payment_id), "why": why})
    return locked


def refund_payment(
    session: Session,
    ctx: Ctx,
    payment_id: uuid.UUID,
    amount: Decimal | None,
    *,
    reason: str | None,
    actor: str,
    idempotency_key: str,
) -> Refund:
    existing = session.scalars(select(Refund).where(Refund.idempotency_key == idempotency_key)).one_or_none()
    if existing is not None:
        session.rollback()
        if existing.payment_id != payment_id:
            raise ShopEaseError(409, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was used for another refund.")
        return existing
    payment = _load(session, payment_id, lock=True)
    if payment.status is not P.SUCCEEDED:
        raise ShopEaseError(409, "PAYMENT_NOT_REFUNDABLE", f"A {payment.status.value} payment can't be refunded.")
    refunded = sum((r.amount for r in payment.refunds if r.status is not RefundStatus.FAILED), Decimal("0"))
    remaining = payment.amount - refunded
    amount = remaining if amount is None else amount
    if amount <= 0 or amount > remaining:
        raise ShopEaseError(409, "PAYMENT_NOT_REFUNDABLE", f"At most {remaining} {payment.currency} can be refunded.")
    refund = Refund(id=uuid.uuid4(), payment_id=payment.id, amount=amount, reason=reason,
                    idempotency_key=idempotency_key)
    session.add(refund)
    session.commit()  # recorded before the provider call

    try:
        result = ctx.provider.refund(str(refund.id), payment.provider_txn_ref, amount, payment.currency)
    except ProviderError:
        result = None
    locked = _load(session, payment_id, lock=True)
    row = session.get(Refund, refund.id, with_for_update=True)
    if result is None:
        row.status = RefundStatus.PROCESSING
        locked.needs_manual_review = True  # refund outcome unknown: a person checks the provider
    elif result.succeeded:
        row.status = RefundStatus.SUCCEEDED
        row.provider_refund_ref = result.provider_reference
        if amount == remaining:
            _set_status(session, locked, P.REFUNDED, StatusSource.API)
    else:
        row.status = RefundStatus.FAILED
    session.commit()
    logger.info("refund processed", extra={"payment_id": str(payment_id), "status": row.status.value, "by": actor})
    return row


# --- Reconciliation and background work ----------------------------------------------------------


def reconcile(session: Session, ctx: Ctx, payment_id: uuid.UUID, force: bool = False) -> Payment:
    """Ask the provider what happened to an unknown outcome. Never charges."""
    payment = _load(session, payment_id)
    session.rollback()
    if payment is None:
        raise payment_not_found(payment_id)
    if payment.status not in (P.INITIATED, P.PROCESSING) or (payment.needs_manual_review and not force):
        return payment
    try:
        result = ctx.provider.get_status(str(payment.id))
    except ProviderError:
        return _mark_unknown(session, ctx.settings, payment_id, StatusSource.RECONCILIATION)
    if result is None:
        # The provider has no record of this charge: it never happened (mock: lost on restart).
        locked = _load(session, payment_id, lock=True)
        if locked.status in (P.INITIATED, P.PROCESSING):
            if locked.status is P.INITIATED:
                _set_status(session, locked, P.PROCESSING, StatusSource.RECONCILIATION)
            _set_status(session, locked, P.FAILED, StatusSource.RECONCILIATION)
            locked.failure_reason = "not_found_at_provider"
        session.commit()
    else:
        apply_charge_result(session, ctx.settings, payment_id, result, StatusSource.RECONCILIATION)
    return report_result(session, ctx, payment_id)


def run_background(session: Session, ctx: Ctx, batch: int = 50) -> dict[str, int]:
    now = utcnow()
    due_reconcile = session.scalars(
        select(Payment.id).where(
            Payment.status == P.PROCESSING, Payment.needs_manual_review.is_(False), Payment.next_reconcile_at <= now
        ).limit(batch)
    ).all()
    # INITIATED for over a minute: the process stopped between recording and charging.
    stale_initiated = session.scalars(
        select(Payment.id).where(Payment.status == P.INITIATED, Payment.created_at <= now - timedelta(minutes=1)).limit(batch)
    ).all()
    due_report = session.scalars(
        select(Payment.id).where(
            Payment.result_reported_at.is_(None),
            Payment.status != P.INITIATED,
            Payment.next_report_at <= now,
            Payment.report_attempts < ctx.settings.max_report_attempts,
        ).limit(batch)
    ).all()
    session.rollback()
    counts = {"reconciled": 0, "reported": 0}
    for payment_id in {*due_reconcile, *stale_initiated}:
        reconcile(session, ctx, payment_id)
        counts["reconciled"] += 1
    for payment_id in due_report:
        if report_result(session, ctx, payment_id).result_reported_at is not None:
            counts["reported"] += 1
    if any(counts.values()):
        logger.info("payment background run", extra=counts)
    return counts
