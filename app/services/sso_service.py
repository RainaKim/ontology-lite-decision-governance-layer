"""
app/services/sso_service.py — Google OAuth2 and Azure AD OIDC helpers.

All SSO credentials (client_id, client_secret, tenant_id) are stored per-company
in the DB (companies table). No global credential env vars are required.

State parameter is a short-lived JWT (10 min) encoding company_id + nonce
for CSRF protection.

Env vars:
  SSO_CALLBACK_BASE_URL  — base URL for callback redirects (default: http://localhost:8000)
  JWT_SECRET             — shared with auth_service (already set)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import jwt
from fastapi import HTTPException, status
from jwt.exceptions import PyJWTError

from app.models.company import Company
from app.services.auth_service import JWT_SECRET, JWT_ALG

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SSO_CALLBACK_BASE_URL: str = os.environ.get(
    "SSO_CALLBACK_BASE_URL", "http://localhost:8000"
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

AZURE_AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
AZURE_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

_STATE_EXPIRES_MINUTES = 10

# ---------------------------------------------------------------------------
# State JWT (CSRF protection)
# ---------------------------------------------------------------------------


def _make_state(company_id: str) -> str:
    """Return a short-lived JWT encoding company_id + nonce."""
    payload = {
        "company_id": company_id,
        "nonce": str(uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _verify_state(state: str) -> str:
    """
    Decode and verify the state JWT.

    Returns company_id on success.
    Raises HTTPException 400 on invalid or expired state.
    """
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALG])
        company_id: Optional[str] = payload.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="Invalid SSO state: missing company_id")
        return company_id
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired SSO state parameter",
        )


# ---------------------------------------------------------------------------
# Authorization URL builders
# ---------------------------------------------------------------------------


def get_google_auth_url(company: Company) -> str:
    """
    Build the Google OAuth2 authorization URL for the given company.

    Raises HTTPException 400 if company lacks SSO credentials.
    """
    if not company.sso_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company is not configured for Google SSO",
        )
    callback_url = f"{SSO_CALLBACK_BASE_URL}/v1/auth/sso/google/callback"
    state = _make_state(company.id)
    params = {
        "client_id": company.sso_client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def get_azure_auth_url(company: Company) -> str:
    """
    Build the Azure AD OIDC authorization URL for the given company.

    Raises HTTPException 400 if company lacks SSO credentials.
    """
    if not company.sso_client_id or not company.sso_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company is not configured for Azure SSO",
        )
    callback_url = f"{SSO_CALLBACK_BASE_URL}/v1/auth/sso/azure/callback"
    state = _make_state(company.id)
    auth_url = AZURE_AUTH_URL.format(tenant=company.sso_tenant_id)
    params = {
        "client_id": company.sso_client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "response_mode": "query",
    }
    return f"{auth_url}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def exchange_google_code(code: str, company: Company) -> dict:
    """
    Exchange authorization code for tokens and fetch user info from Google.

    Returns dict with keys: email, name, sub.
    Raises HTTPException 502 on upstream errors.
    """
    callback_url = f"{SSO_CALLBACK_BASE_URL}/v1/auth/sso/google/callback"
    with httpx.Client(timeout=10) as client:
        # Exchange code for tokens
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": company.sso_client_id,
                "client_secret": company.sso_client_secret,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to exchange Google authorization code",
            )
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google token response missing access_token",
            )

        # Fetch user info
        info_resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch Google user info",
            )
        info = info_resp.json()

    email = info.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google user info missing email",
        )
    return {
        "email": email,
        "name": info.get("name"),
        "sub": info.get("sub"),
    }


def exchange_azure_code(code: str, company: Company) -> dict:
    """
    Exchange authorization code for tokens with Azure AD and decode the id_token.

    Returns dict with keys: email, name, sub.
    Raises HTTPException 502 on upstream errors.
    """
    callback_url = f"{SSO_CALLBACK_BASE_URL}/v1/auth/sso/azure/callback"
    token_url = AZURE_TOKEN_URL.format(tenant=company.sso_tenant_id)
    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            token_url,
            data={
                "code": code,
                "client_id": company.sso_client_id,
                "client_secret": company.sso_client_secret,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
                "scope": "openid email profile",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to exchange Azure authorization code",
            )
        tokens = token_resp.json()

    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Azure token response missing id_token",
        )

    # Decode without signature verification — Azure public key rotation is
    # complex for an MVP. In production, verify against Azure JWKS endpoint.
    try:
        claims = jwt.decode(
            id_token,
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to decode Azure id_token",
        )

    email = claims.get("email") or claims.get("preferred_username")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Azure id_token missing email claim",
        )
    return {
        "email": email,
        "name": claims.get("name"),
        "sub": claims.get("sub"),
    }


# ---------------------------------------------------------------------------
# Public helper used by SSO router
# ---------------------------------------------------------------------------


def verify_state(state: str) -> str:
    """Public alias for _verify_state — returns company_id."""
    return _verify_state(state)


# ---------------------------------------------------------------------------
# Global Google OAuth (env-var credentials, no per-company config needed)
# ---------------------------------------------------------------------------

def _make_global_state() -> str:
    """Short-lived JWT with just a nonce for CSRF protection (no company_id)."""
    payload = {
        "nonce": str(uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_EXPIRES_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _verify_global_state(state: str) -> None:
    """Verify the global state JWT. Raises HTTPException 400 if invalid."""
    try:
        jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALG])
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )


def get_global_google_auth_url() -> str:
    """
    Build the Google OAuth2 authorization URL using global env-var credentials.

    Raises HTTPException 503 if GOOGLE_CLIENT_ID is not configured.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server (GOOGLE_CLIENT_ID missing)",
        )
    callback_url = f"{SSO_CALLBACK_BASE_URL}/v1/auth/google/callback"
    state = _make_global_state()
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_global_google_code(code: str, state: str) -> dict:
    """
    Verify state, exchange code for tokens, and return user info.

    Returns dict with keys: email, name, sub.
    Raises HTTPException on any failure.
    """
    _verify_global_state(state)

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server",
        )

    callback_url = f"{SSO_CALLBACK_BASE_URL}/v1/auth/google/callback"
    with httpx.Client(timeout=10) as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to exchange Google authorization code",
            )
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google token response missing access_token",
            )

        info_resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch Google user info",
            )
        info = info_resp.json()

    email = info.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google user info missing email",
        )
    return {"email": email, "name": info.get("name"), "sub": info.get("sub")}
