"""Pydantic request/response schemas for auth_service (rest_api_notes.md §3.2)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


class RegisterRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'email': 'customer@example.com', 'password': '<at-least-12-characters>'}]})

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'email': 'customer@example.com', 'password': '<password>'}]})

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthUserRead(BaseModel):
    """Public view of a login identity. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID = Field(validation_alias="id")
    email: EmailStr
    role: Role
    created_at: datetime


class RoleUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'role': 'admin'}]})

    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'refresh_token': '<refresh-token-from-login>'}]})

    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    """Omit refresh_token to end every session of the caller."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'refresh_token': '<refresh-token-to-revoke>'}]})

    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class PasswordChange(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'current_password': '<current-password>', 'new_password': '<new-password-12-plus>'}]})

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class ServiceTokenRequest(BaseModel):
    """Client-credentials exchange for internal services (ADR-08)."""

    model_config = ConfigDict(json_schema_extra={"examples": [{'client_id': 'svc:order', 'client_secret': '<client-secret>', 'scope': 'products:read'}]})

    client_id: str = Field(min_length=1, max_length=64)
    client_secret: str = Field(min_length=1, max_length=256)
    scope: str | None = Field(default=None, max_length=512, description="Space-separated subset of allowed scopes")


class ServiceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str
