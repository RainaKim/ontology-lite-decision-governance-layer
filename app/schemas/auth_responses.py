"""
app/schemas/auth_responses.py — Outbound response bodies for auth endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """Public user representation. Never includes password_hash or sso_client_secret."""

    model_config = ConfigDict(from_attributes=True)

    # Core user fields (from User ORM)
    id: str
    email: str
    name: Optional[str] = None
    role: str
    department_name: Optional[str] = None
    company_id: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime

    # Company-derived (None when user has no linked DB company)
    company_name: Optional[str] = None
    license_tier: Optional[str] = None
    auth_method: Optional[str] = None   # LOCAL | GOOGLE_SSO | AZURE_SSO | SAML

    # RBAC-derived permission list
    permissions: list[str] = []


class AuthResponse(BaseModel):
    """Returned on signup, login, and SSO callback."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
