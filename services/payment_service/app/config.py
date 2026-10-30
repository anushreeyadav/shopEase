"""Payment Service configuration, read from environment variables (and .env in development)."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from sqlalchemy.engine import URL

from shopease_shared import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "payment_service"

    # This service's own logical database (payment_db). No other service receives these credentials.
    mysql_host: str = Field(default="localhost", validation_alias=AliasChoices("MYSQL_HOST"))
    mysql_port: int = Field(default=3306, validation_alias=AliasChoices("MYSQL_PORT"))
    db_name: str = Field(default="payment_db", validation_alias=AliasChoices("PAYMENT_DB_NAME"))
    # Runtime user: SELECT/INSERT/UPDATE/DELETE on payment_db only. Used by the running service.
    db_user: str = Field(default="payment_svc", validation_alias=AliasChoices("PAYMENT_DB_USER"))
    db_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("PAYMENT_DB_PASSWORD")
    )
    # Migration user: DDL on payment_db only. Used by Alembic, never by the running service.
    db_migration_user: str = Field(
        default="payment_migrator", validation_alias=AliasChoices("PAYMENT_DB_MIGRATION_USER")
    )
    db_migration_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("PAYMENT_DB_MIGRATION_PASSWORD")
    )
    db_connect_timeout_seconds: int = Field(
        default=3, validation_alias=AliasChoices("DB_CONNECT_TIMEOUT_SECONDS")
    )
    db_pool_size: int = Field(default=5, validation_alias=AliasChoices("DB_POOL_SIZE"))

    # Provider adapter. Only "mock" exists (development and tests; refused in production).
    payment_provider: str = Field(default="mock", validation_alias=AliasChoices("PAYMENT_PROVIDER"))

    # Dependencies (internal network addresses, not the gateway).
    auth_service_url: str = Field(default="http://localhost:8001", validation_alias=AliasChoices("AUTH_SERVICE_URL"))
    order_service_url: str = Field(default="http://localhost:8004", validation_alias=AliasChoices("ORDER_SERVICE_URL"))
    # Client credentials for service tokens (ADR-08). Register with:
    #   python scripts/auth_cli.py create-service-client svc:payment --scope orders:read --scope orders:payment
    service_client_id: str = Field(default="svc:payment", validation_alias=AliasChoices("PAYMENT_SERVICE_CLIENT_ID"))
    service_client_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("PAYMENT_SERVICE_CLIENT_SECRET")
    )

    # Timeouts in seconds (docs/service_communication.md §3).
    connect_timeout: float = Field(default=0.5, validation_alias=AliasChoices("DEPENDENCY_CONNECT_TIMEOUT_SECONDS"))
    payable_timeout: float = Field(default=1.5, validation_alias=AliasChoices("PAYABLE_TIMEOUT_SECONDS"))
    payment_result_timeout: float = Field(default=4.0, validation_alias=AliasChoices("PAYMENT_RESULT_TIMEOUT_SECONDS"))
    service_token_timeout: float = Field(default=2.0, validation_alias=AliasChoices("SERVICE_TOKEN_TIMEOUT_SECONDS"))

    # Background job: reconcile unknown outcomes and retry result reports; 0 disables it.
    sweep_seconds: int = Field(default=15, ge=0, validation_alias=AliasChoices("PAYMENT_SWEEP_SECONDS"))
    # Reconciliation schedule after an unknown outcome; after the last one: manual review.
    reconcile_schedule_seconds: list[int] = Field(
        default=[30, 120, 600, 3600, 21600, 86400], validation_alias=AliasChoices("RECONCILE_SCHEDULE_SECONDS")
    )
    max_report_attempts: int = Field(default=10, ge=1, validation_alias=AliasChoices("MAX_REPORT_ATTEMPTS"))

    def _url(self, user: str, password: SecretStr) -> URL:
        # URL objects mask the password when printed or logged.
        return URL.create(
            "mysql+pymysql",
            username=user,
            password=password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

    @property
    def database_url(self) -> URL:
        return self._url(self.db_user, self.db_password)

    @property
    def migration_database_url(self) -> URL:
        if not self.db_migration_password.get_secret_value():
            raise RuntimeError(
                "PAYMENT_DB_MIGRATION_USER and PAYMENT_DB_MIGRATION_PASSWORD must be set to run migrations."
            )
        return self._url(self.db_migration_user, self.db_migration_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
