"""Order Service configuration, read from environment variables (and .env in development)."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from sqlalchemy.engine import URL

from shopease_shared import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "order_service"

    # This service's own logical database (order_db). No other service receives these credentials.
    mysql_host: str = Field(default="localhost", validation_alias=AliasChoices("MYSQL_HOST"))
    mysql_port: int = Field(default=3306, validation_alias=AliasChoices("MYSQL_PORT"))
    db_name: str = Field(default="order_db", validation_alias=AliasChoices("ORDER_DB_NAME"))
    # Runtime user: SELECT/INSERT/UPDATE/DELETE on order_db only. Used by the running service.
    db_user: str = Field(default="order_svc", validation_alias=AliasChoices("ORDER_DB_USER"))
    db_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("ORDER_DB_PASSWORD")
    )
    # Migration user: DDL on order_db only. Used by Alembic, never by the running service.
    db_migration_user: str = Field(
        default="order_migrator", validation_alias=AliasChoices("ORDER_DB_MIGRATION_USER")
    )
    db_migration_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("ORDER_DB_MIGRATION_PASSWORD")
    )
    db_connect_timeout_seconds: int = Field(
        default=3, validation_alias=AliasChoices("DB_CONNECT_TIMEOUT_SECONDS")
    )
    db_pool_size: int = Field(default=5, validation_alias=AliasChoices("DB_POOL_SIZE"))

    # Dependencies (internal network addresses, not the gateway).
    auth_service_url: str = Field(default="http://localhost:8001", validation_alias=AliasChoices("AUTH_SERVICE_URL"))
    user_service_url: str = Field(default="http://localhost:8002", validation_alias=AliasChoices("USER_SERVICE_URL"))
    product_service_url: str = Field(
        default="http://localhost:8003", validation_alias=AliasChoices("PRODUCT_SERVICE_URL")
    )
    # Client credentials for service tokens (ADR-08). Register with:
    #   python scripts/auth_cli.py create-service-client svc:order --scope products:read \
    #       --scope inventory:reserve --scope addresses:read
    service_client_id: str = Field(default="svc:order", validation_alias=AliasChoices("ORDER_SERVICE_CLIENT_ID"))
    service_client_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("ORDER_SERVICE_CLIENT_SECRET")
    )

    # Timeouts in seconds (docs/service_communication.md §3). Connect timeouts fail fast.
    connect_timeout: float = Field(default=0.5, validation_alias=AliasChoices("DEPENDENCY_CONNECT_TIMEOUT_SECONDS"))
    price_check_timeout: float = Field(default=1.5, validation_alias=AliasChoices("PRICE_CHECK_TIMEOUT_SECONDS"))
    address_timeout: float = Field(default=1.5, validation_alias=AliasChoices("ADDRESS_TIMEOUT_SECONDS"))
    reserve_timeout: float = Field(default=2.0, validation_alias=AliasChoices("RESERVE_TIMEOUT_SECONDS"))
    confirm_release_timeout: float = Field(default=1.5, validation_alias=AliasChoices("CONFIRM_RELEASE_TIMEOUT_SECONDS"))
    service_token_timeout: float = Field(default=2.0, validation_alias=AliasChoices("SERVICE_TOKEN_TIMEOUT_SECONDS"))
    # Whole POST /api/orders budget; must stay below the gateway's upstream timeout.
    create_deadline_seconds: float = Field(default=7.0, validation_alias=AliasChoices("ORDER_CREATE_DEADLINE_SECONDS"))

    # Background recovery job (expiry, stuck orders, pending stock releases); 0 disables it.
    sweep_seconds: int = Field(default=30, ge=0, validation_alias=AliasChoices("ORDER_SWEEP_SECONDS"))
    # A PENDING order older than this was abandoned mid-checkout (e.g. a crash): release and cancel.
    stuck_pending_seconds: int = Field(default=120, ge=30, validation_alias=AliasChoices("STUCK_PENDING_SECONDS"))

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
                "ORDER_DB_MIGRATION_USER and ORDER_DB_MIGRATION_PASSWORD must be set to run migrations."
            )
        return self._url(self.db_migration_user, self.db_migration_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
