"""Payment provider adapter boundary.

payment_service talks to providers only through this interface. A real gateway integration
implements the same three operations; nothing else in the service changes.

Rules every adapter must follow:
- `charge` and `refund` are called with an idempotency key (our payment or refund ID), so the
  provider executes each at most once even if the request is sent again.
- Raise ProviderUnavailable only when the request **certainly did not reach** the provider
  (connection refused, circuit open). Raise ProviderTimeout when it **may have** been
  processed: the caller then records an unknown outcome and reconciles with `get_status`.
- Return only non-sensitive data: a provider reference, card brand and last four digits.
"""

import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class ChargeOutcome(enum.StrEnum):
    SUCCEEDED = "SUCCEEDED"  # the provider accepted and captured the payment
    DECLINED = "DECLINED"  # definitive refusal (card declined, insufficient funds, ...)
    PENDING = "PENDING"  # accepted for processing, final outcome not known yet


@dataclass(frozen=True)
class ChargeResult:
    outcome: ChargeOutcome
    provider_reference: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None
    decline_code: str | None = None


@dataclass(frozen=True)
class RefundResult:
    succeeded: bool
    provider_reference: str | None = None
    failure_code: str | None = None


class ProviderError(Exception):
    pass


class ProviderTimeout(ProviderError):
    """The request may have been processed: the outcome is unknown. Never retry a charge."""


class ProviderUnavailable(ProviderError):
    """The request certainly did not reach the provider: nothing was charged."""


class InvalidPaymentMethod(ProviderError):
    """The payment-method token is not one this provider accepts."""


class PaymentProvider(Protocol):
    name: str

    def validate_token(self, payment_method_token: str) -> None:
        """Raise InvalidPaymentMethod before anything is stored or charged."""

    def charge(self, idempotency_key: str, amount: Decimal, currency: str, payment_method_token: str) -> ChargeResult:
        ...

    def get_status(self, idempotency_key: str) -> ChargeResult | None:
        """The provider's record of a charge, or None if it has no record of that key."""

    def refund(self, idempotency_key: str, provider_reference: str, amount: Decimal, currency: str) -> RefundResult:
        ...
