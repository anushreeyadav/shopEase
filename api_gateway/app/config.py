"""API Gateway configuration, read from environment variables (and .env in development)."""

from functools import lru_cache
from typing import NamedTuple

import httpx
from pydantic import AliasChoices, Field

from shopease_shared import BaseServiceSettings


class Upstream(NamedTuple):
    prefix: str
    service: str
    base_url: str
    read_timeout: float
    connect_timeout: float

    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.read_timeout, connect=self.connect_timeout)


class Settings(BaseServiceSettings):
    service_name: str = "api_gateway"

    auth_service_url: str = Field(
        default="http://localhost:8001", validation_alias=AliasChoices("AUTH_SERVICE_URL")
    )
    user_service_url: str = Field(
        default="http://localhost:8002", validation_alias=AliasChoices("USER_SERVICE_URL")
    )
    product_service_url: str = Field(
        default="http://localhost:8003", validation_alias=AliasChoices("PRODUCT_SERVICE_URL")
    )
    order_service_url: str = Field(
        default="http://localhost:8004", validation_alias=AliasChoices("ORDER_SERVICE_URL")
    )
    payment_service_url: str = Field(
        default="http://localhost:8005", validation_alias=AliasChoices("PAYMENT_SERVICE_URL")
    )

    upstream_connect_timeout_seconds: float = Field(
        default=1.0, validation_alias=AliasChoices("UPSTREAM_CONNECT_TIMEOUT_SECONDS")
    )
    # Read timeouts per upstream (docs/service_communication.md §3). Each must exceed the
    # service's own deadline: orders 7s (+ compensation), payments ~18s with a real provider.
    upstream_timeout_seconds: float = Field(
        default=5.0, validation_alias=AliasChoices("UPSTREAM_TIMEOUT_SECONDS")
    )
    order_upstream_timeout_seconds: float = Field(
        default=10.0, validation_alias=AliasChoices("ORDER_UPSTREAM_TIMEOUT_SECONDS")
    )
    payment_upstream_timeout_seconds: float = Field(
        default=20.0, validation_alias=AliasChoices("PAYMENT_UPSTREAM_TIMEOUT_SECONDS")
    )
    # Larger request bodies are refused with 413 before reaching any service.
    max_request_body_bytes: int = Field(
        default=1_048_576, ge=1024, validation_alias=AliasChoices("MAX_REQUEST_BODY_BYTES")
    )

    # Requests per client IP per minute; 0 disables that limit. The auth limit applies to
    # POST /api/auth/register, /login and /refresh; the default limit to everything else.
    rate_limit_auth_per_minute: int = Field(
        default=20, ge=0, validation_alias=AliasChoices("RATE_LIMIT_AUTH_PER_MINUTE")
    )
    rate_limit_default_per_minute: int = Field(
        default=0, ge=0, validation_alias=AliasChoices("RATE_LIMIT_DEFAULT_PER_MINUTE")
    )

    # Comma-separated browser origins. Empty (the default) means CORS is not enabled at all.
    cors_allowed_origins: str = Field(default="", validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS"))

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def upstreams(self) -> list[Upstream]:
        """The route map (rest_api_notes.md Part 2). /internal/* is deliberately absent."""
        default, connect = self.upstream_timeout_seconds, self.upstream_connect_timeout_seconds
        return [
            Upstream("/api/auth", "auth_service", self.auth_service_url, default, connect),
            Upstream("/api/users", "user_service", self.user_service_url, default, connect),
            Upstream("/api/products", "product_service", self.product_service_url, default, connect),
            Upstream("/api/categories", "product_service", self.product_service_url, default, connect),
            Upstream("/api/orders", "order_service", self.order_service_url, self.order_upstream_timeout_seconds, connect),
            Upstream(
                "/api/payments", "payment_service", self.payment_service_url, self.payment_upstream_timeout_seconds, connect
            ),
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
