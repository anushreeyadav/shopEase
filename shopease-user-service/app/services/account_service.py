"""Business logic for the caller's account: identity, contact details, and deactivation.

Two separate statuses are involved:
- The Authentication Service account (login, email, role, its own is_active). This service
  only reads it from the verify-token response and never changes it. A caller whose account
  is inactive is rejected with 403 before any code here runs.
- The local User Service profile (user_profiles.is_active). deactivate_account sets it to
  false. The profile and its addresses are kept, and every profile, address and account
  operation then fails with ProfileDeactivatedError.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser
from app.models.user_model import UserProfile
from app.services import user_service


@dataclass(frozen=True)
class AccountOverview:
    account: AuthenticatedUser
    profile: UserProfile | None  # None until the caller creates a profile


def get_account(db: Session, user: AuthenticatedUser) -> AccountOverview:
    try:
        profile = user_service.get_active_profile(db, user.auth_user_id)
    except user_service.ProfileNotFoundError:
        profile = None
    return AccountOverview(account=user, profile=profile)


def update_contact(db: Session, auth_user_id: int, phone_number: str | None) -> UserProfile:
    """Change the contact phone number. The email address belongs to the Authentication Service."""
    return user_service.update_profile(db, auth_user_id, {"phone_number": phone_number})


def deactivate_account(db: Session, auth_user_id: int) -> UserProfile:
    """Deactivate the local profile only. Makes no call to the Authentication Service."""
    return user_service.deactivate_profile(db, auth_user_id)
