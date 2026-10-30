"""Settings common to every service. Each service subclasses this with its own fields."""

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    # Read from the process environment first, then from .env in the working directory.
    # Unknown variables are ignored because all services share one .env in development.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str
    version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = Field(
        default="development", validation_alias=AliasChoices("APP_ENV")
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL")
    )
    # Swagger UI and /openapi.json. Disable outside development (internal network only).
    docs_enabled: bool = Field(default=True, validation_alias=AliasChoices("DOCS_ENABLED"))

    # Token verification (every component verifies locally with auth_service's public keys).
    jwt_issuer: str = Field(default="shopease-auth", validation_alias=AliasChoices("JWT_ISSUER"))
    # Audience of user access tokens (public API) and of service tokens (/internal/*).
    jwt_audience: str = Field(default="shopease-api", validation_alias=AliasChoices("JWT_AUDIENCE"))
    jwt_service_audience: str = Field(
        default="shopease-internal", validation_alias=AliasChoices("JWT_SERVICE_AUDIENCE")
    )
    jwks_url: str = Field(
        default="http://localhost:8001/api/auth/.well-known/jwks.json",
        validation_alias=AliasChoices("JWKS_URL"),
    )
    jwks_cache_seconds: int = Field(default=300, validation_alias=AliasChoices("JWKS_CACHE_SECONDS"))
    jwt_leeway_seconds: int = Field(default=30, validation_alias=AliasChoices("JWT_LEEWAY_SECONDS"))
