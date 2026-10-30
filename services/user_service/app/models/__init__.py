"""user_service models. Importing this package registers every table on Base.metadata."""

from app.models.base import Base
from app.models.profile import UserAddress, UserProfile

__all__ = ["Base", "UserAddress", "UserProfile"]
