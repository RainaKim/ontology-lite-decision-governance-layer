"""
app/schemas/auth_requests.py — Inbound request bodies for auth endpoints.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

_VALID_ROLES = {"ADMIN", "MANAGER", "USER"}


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")
    name: Optional[str] = Field(default=None, max_length=200)
    role: str = Field(default="USER", description="ADMIN | MANAGER | USER")

    @field_validator("email", mode="before")
    @classmethod
    def _lowercase_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("role", mode="before")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return upper


class UpdateProfileRequest(BaseModel):
    """Body for PUT /v1/me — all fields optional, only sent fields are updated."""

    name: Optional[str] = Field(default=None, max_length=200)
    department_name: Optional[str] = Field(default=None, max_length=100)
    company_id: Optional[str] = Field(default=None, max_length=36)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _lowercase_email(cls, v: str) -> str:
        return v.strip().lower()
