"""Provider selection. Only the MOCK provider exists; a real gateway is a future adapter."""

from app.config import Settings
from app.providers.base import PaymentProvider
from app.providers.mock import MockProvider


def build_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_provider == "mock":
        if settings.environment == "production":
            raise RuntimeError(
                "PAYMENT_PROVIDER=mock is for development and tests only; it can't run with APP_ENV=production."
            )
        return MockProvider()
    raise RuntimeError(f"Unknown PAYMENT_PROVIDER {settings.payment_provider!r}; only 'mock' is implemented.")
