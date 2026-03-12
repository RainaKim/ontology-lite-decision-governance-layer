"""
app/routers/sso.py — SSO authorization + callback endpoints.

Routes:
  GET /v1/auth/sso/google/authorize?company_id=...  → {"authorization_url": "..."}
  GET /v1/auth/sso/google/callback?code=...&state=...  → AuthResponse
  GET /v1/auth/sso/azure/authorize?company_id=...   → {"authorization_url": "..."}
  GET /v1/auth/sso/azure/callback?code=...&state=...   → AuthResponse
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import company_repository, user_repository
from app.schemas.auth_responses import AuthResponse
from app.services import sso_service
from app.services.auth_service import create_access_token
from app.services.user_service import build_user_response

router = APIRouter(prefix="/v1/auth/sso", tags=["sso"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_company_or_404(db: Session, company_id: str):
    company = company_repository.get_by_id(db, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company '{company_id}' not found",
        )
    if company.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company account is suspended or deleted",
        )
    return company


def _build_auth_response(db: Session, email: str, name, company_id: str) -> AuthResponse:
    user = user_repository.find_or_create_sso_user(
        db, email=email, name=name, company_id=company_id
    )
    user_repository.set_last_login(db, user.id)
    token = create_access_token(sub=user.id)
    return AuthResponse(
        access_token=token,
        user=build_user_response(user, db),
    )


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


@router.get("/google/authorize", summary="Get Google OAuth2 authorization URL")
def google_authorize(company_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Returns the Google OAuth2 authorization URL for the given company.
    Redirect the user's browser to this URL.
    """
    company = _get_company_or_404(db, company_id)
    if company.auth_type != "GOOGLE_SSO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company is not configured for Google SSO",
        )
    url = sso_service.get_google_auth_url(company)
    return {"authorization_url": url}


@router.get(
    "/google/callback",
    response_model=AuthResponse,
    summary="Google OAuth2 callback — exchanges code for JWT",
)
def google_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """
    OAuth2 callback from Google.
    Verifies state, exchanges code, finds or creates user, returns JWT.
    """
    company_id = sso_service.verify_state(state)
    company = _get_company_or_404(db, company_id)
    user_info = sso_service.exchange_google_code(code, company)
    return _build_auth_response(db, user_info["email"], user_info.get("name"), company_id)


# ---------------------------------------------------------------------------
# Azure AD
# ---------------------------------------------------------------------------


@router.get("/azure/authorize", summary="Get Azure AD OIDC authorization URL")
def azure_authorize(company_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Returns the Azure AD OIDC authorization URL for the given company.
    Redirect the user's browser to this URL.
    """
    company = _get_company_or_404(db, company_id)
    if company.auth_type != "AZURE_SSO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company is not configured for Azure SSO",
        )
    url = sso_service.get_azure_auth_url(company)
    return {"authorization_url": url}


@router.get(
    "/azure/callback",
    response_model=AuthResponse,
    summary="Azure AD OIDC callback — exchanges code for JWT",
)
def azure_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """
    OIDC callback from Azure AD.
    Verifies state, exchanges code, finds or creates user, returns JWT.
    """
    company_id = sso_service.verify_state(state)
    company = _get_company_or_404(db, company_id)
    user_info = sso_service.exchange_azure_code(code, company)
    return _build_auth_response(db, user_info["email"], user_info.get("name"), company_id)
