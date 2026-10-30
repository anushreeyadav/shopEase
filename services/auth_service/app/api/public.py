"""Public /api/auth routes (rest_api_notes.md §3.2). Reached through the gateway."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, Response

from app import accounts
from app.dependencies import DbSession, SettingsDep
from app.schemas import (
    AuthUserRead,
    LoginRequest,
    LogoutRequest,
    PasswordChange,
    RefreshRequest,
    RegisterRequest,
    RoleUpdate,
    TokenResponse,
)
from app.security.tokens import TokenIssuer
from shopease_shared import ShopEaseError
from shopease_shared.security import AdminUser, CurrentUser

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_issuer(request: Request) -> TokenIssuer:
    return request.app.state.token_issuer


Issuer = Annotated[TokenIssuer, Depends(get_issuer)]


@router.post("/register", status_code=201, response_model=AuthUserRead, summary="Register a customer account")
def register(body: RegisterRequest, session: DbSession, response: Response) -> AuthUserRead:
    user = accounts.register(session, body.email, body.password)
    response.headers["Location"] = "/api/users/me"
    return AuthUserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for an access and refresh token")
def login(body: LoginRequest, session: DbSession, settings: SettingsDep, issuer: Issuer) -> dict:
    return accounts.login(session, settings, issuer, body.email, body.password)


@router.post("/refresh", response_model=TokenResponse, summary="Rotate a refresh token for a new access token")
def refresh(body: RefreshRequest, session: DbSession, issuer: Issuer) -> dict:
    return accounts.refresh(session, issuer, body.refresh_token)


@router.post("/logout", status_code=204, summary="Revoke a refresh token, or all of the caller's sessions")
def logout(user: CurrentUser, session: DbSession, body: Annotated[LogoutRequest | None, Body()] = None) -> None:
    accounts.logout(session, user.user_id, body.refresh_token if body else None)


@router.put("/password", status_code=204, summary="Change the caller's password (ends all sessions)")
def change_password(body: PasswordChange, user: CurrentUser, session: DbSession) -> None:
    if body.new_password == body.current_password:
        raise ShopEaseError(422, "VALIDATION_ERROR", "The new password must differ from the current one.")
    accounts.change_password(session, user.user_id, body.current_password, body.new_password)


@router.get("/.well-known/jwks.json", summary="Public keys for verifying tokens")
def jwks(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"keys": [request.app.state.signing_key.public_jwk()]}


@router.patch("/users/{user_id}/role", response_model=AuthUserRead, summary="Change a user's role (admin)")
def change_role(user_id: UUID, body: RoleUpdate, admin: AdminUser, session: DbSession) -> AuthUserRead:
    return AuthUserRead.model_validate(accounts.set_role(session, user_id, body.role, admin.user_id))
