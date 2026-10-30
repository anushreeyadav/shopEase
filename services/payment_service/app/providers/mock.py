"""MOCK payment provider: for local development and automated tests ONLY.

It moves no money, contacts no network service and has no relationship with any card
network or bank. Every "charge" is an entry in a Python dictionary inside this process.
References start with `mock_` so they can never be mistaken for real ones. The service
refuses to start with this provider when APP_ENV=production (app/providers/__init__.py).

Behaviour is chosen by the payment-method token (no card data is ever accepted):

| Token                         | Simulated provider behaviour                                        |
|-------------------------------|---------------------------------------------------------------------|
| mock_tok_success              | Accepted (brand MOCKVISA, last4 0000)                               |
| mock_tok_decline              | Declined: card_declined                                             |
| mock_tok_insufficient_funds   | Declined: insufficient_funds                                        |
| mock_tok_timeout              | Accepted, but the response is lost (timeout): reconcile → SUCCEEDED |
| mock_tok_timeout_declined     | Declined, but the response is lost (timeout): reconcile → FAILED    |
| mock_tok_pending              | Accepted for processing; status stays PENDING                       |
| mock_tok_unavailable          | Provider unreachable before the request is sent (nothing charged)   |
| mock_tok_duplicate_ref        | Accepted, but reuses the reference `mock_txn_duplicate`             |
| mock_tok_amount_mismatch      | Accepted, but reports a captured amount 1.00 higher                 |

Charges are idempotent per key, like a real provider: sending the same key again returns
the first result and never "charges" twice. State lives in memory and is lost on restart;
`get_status` then returns None, which payment_service treats as "never charged" for this
mock only (see docs/payment_processing.md).
"""

import threading
import uuid
from decimal import Decimal

from app.providers.base import (
    ChargeOutcome,
    ChargeResult,
    InvalidPaymentMethod,
    ProviderTimeout,
    ProviderUnavailable,
    RefundResult,
)

SCENARIOS = {
    "mock_tok_success",
    "mock_tok_decline",
    "mock_tok_insufficient_funds",
    "mock_tok_timeout",
    "mock_tok_timeout_declined",
    "mock_tok_pending",
    "mock_tok_unavailable",
    "mock_tok_duplicate_ref",
    "mock_tok_amount_mismatch",
}


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self._charges: dict[str, ChargeResult] = {}
        self._refunds: dict[str, RefundResult] = {}
        self.charge_calls: dict[str, int] = {}  # how often each key was *executed* (tests)
        self._lock = threading.Lock()

    def validate_token(self, payment_method_token: str) -> None:
        if payment_method_token not in SCENARIOS:
            raise InvalidPaymentMethod("unknown mock payment-method token")

    def charge(self, idempotency_key: str, amount: Decimal, currency: str, payment_method_token: str) -> ChargeResult:
        self.validate_token(payment_method_token)
        if payment_method_token == "mock_tok_unavailable":
            raise ProviderUnavailable("mock provider unreachable")
        with self._lock:
            if idempotency_key in self._charges:  # idempotent replay: no second charge
                result = self._charges[idempotency_key]
            else:
                result = self._decide(amount, currency, payment_method_token)
                self._charges[idempotency_key] = result
                self.charge_calls[idempotency_key] = self.charge_calls.get(idempotency_key, 0) + 1
        if payment_method_token in ("mock_tok_timeout", "mock_tok_timeout_declined"):
            raise ProviderTimeout("mock: response lost after the request was processed")
        return result

    @staticmethod
    def _decide(amount: Decimal, currency: str, token: str) -> ChargeResult:
        card = {"card_brand": "MOCKVISA", "card_last4": "0000"}
        reference = f"mock_txn_{uuid.uuid4().hex[:16]}"
        if token in ("mock_tok_decline", "mock_tok_timeout_declined"):
            return ChargeResult(ChargeOutcome.DECLINED, decline_code="card_declined", **card)
        if token == "mock_tok_insufficient_funds":
            return ChargeResult(ChargeOutcome.DECLINED, decline_code="insufficient_funds", **card)
        if token == "mock_tok_pending":
            return ChargeResult(ChargeOutcome.PENDING, provider_reference=reference, amount=amount, currency=currency)
        if token == "mock_tok_duplicate_ref":
            reference = "mock_txn_duplicate"
        if token == "mock_tok_amount_mismatch":
            amount = amount + Decimal("1.00")
        return ChargeResult(ChargeOutcome.SUCCEEDED, provider_reference=reference, amount=amount,
                            currency=currency, **card)

    def get_status(self, idempotency_key: str) -> ChargeResult | None:
        with self._lock:
            return self._charges.get(idempotency_key)

    def refund(self, idempotency_key: str, provider_reference: str, amount: Decimal, currency: str) -> RefundResult:
        with self._lock:
            if idempotency_key not in self._refunds:
                self._refunds[idempotency_key] = RefundResult(True, f"mock_rfnd_{uuid.uuid4().hex[:16]}")
            return self._refunds[idempotency_key]
