"""Thin cross-cutting helpers shared by every ShopEase service.

Only infrastructure lives here: logging, request correlation IDs, the error
envelope and health routes. Business logic, models and database sessions belong
to the service that owns them (ADR-02, ADR-14).
"""

from shopease_shared.app import install_common
from shopease_shared.errors import ShopEaseError, not_implemented
from shopease_shared.health import build_health_router
from shopease_shared.log_config import configure_logging
from shopease_shared.settings import BaseServiceSettings

__all__ = [
    "BaseServiceSettings",
    "ShopEaseError",
    "build_health_router",
    "configure_logging",
    "install_common",
    "not_implemented",
]
