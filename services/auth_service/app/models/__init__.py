"""auth_service models. Importing this package registers every table on Base.metadata."""

from app.models.auth import AuthUser, RefreshToken, Role, ServiceClient, UserStatus
from app.models.base import Base

__all__ = ["AuthUser", "Base", "RefreshToken", "Role", "ServiceClient", "UserStatus"]
