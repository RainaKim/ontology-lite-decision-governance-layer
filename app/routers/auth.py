"""
app/routers/auth.py — Authentication + profile endpoints.

Routes:
  POST /v1/auth/signup  → AuthResponse  (201)
  POST /v1/auth/login   → AuthResponse  (200)
  GET  /v1/me           → UserResponse  (200, requires Bearer)
  PUT  /v1/me           → UserResponse  (200, requires Bearer)

Entirely isolated from the existing /v1/decisions and /v1/companies routes.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import company_repository, user_repository
from app.schemas.auth_requests import LoginRequest, SignupRequest, UpdateProfileRequest
from app.schemas.auth_responses import AuthResponse, UserResponse
from app.services import sso_service, user_service
from app.services.auth_service import create_access_token
from app.services.user_service import build_user_response

router = APIRouter(prefix="/v1", tags=["auth"])


# ---------------------------------------------------------------------------
# POST /v1/auth/signup
# ---------------------------------------------------------------------------


@router.post(
    "/auth/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """
    Register with email + password.
    Returns a Bearer access token on success.

    - **409** if email is already registered.
    """
    from app.services.auth_service import create_access_token

    user = user_service.signup(
        db=db,
        email=body.email,
        password=body.password,
        name=body.name,
        role=body.role,
    )
    token = create_access_token(sub=user.id)
    return AuthResponse(
        access_token=token,
        user=build_user_response(user, db),
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Authenticate and receive a Bearer token",
)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """
    Exchange email + password for a Bearer access token.

    - **401** if credentials are invalid.
    - **403** if account is inactive.
    """
    token, user = user_service.login(
        db=db,
        email=body.email,
        password=body.password,
    )
    return AuthResponse(
        access_token=token,
        user=build_user_response(user, db),
    )


# ---------------------------------------------------------------------------
# GET /v1/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the currently authenticated user's profile",
)
def me(
    current_user=Depends(user_service.get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Returns the profile of the bearer-authenticated user.

    - **401** if token is missing, invalid, or expired.
    - **403** if account is inactive.
    """
    return build_user_response(current_user, db)


# ---------------------------------------------------------------------------
# PUT /v1/me
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /v1/auth/google/authorize
# ---------------------------------------------------------------------------


@router.get(
    "/auth/google",
    summary="Redirect to Google OAuth2 login",
    response_class=RedirectResponse,
)
def google_authorize() -> RedirectResponse:
    """
    Redirects the browser directly to Google OAuth2 login page.

    Requires GOOGLE_CLIENT_ID env var to be set.
    - **503** if Google OAuth is not configured on this server.
    """
    url = sso_service.get_global_google_auth_url()
    return RedirectResponse(url, status_code=302)


# ---------------------------------------------------------------------------
# GET /v1/auth/google/callback
# ---------------------------------------------------------------------------


@router.get(
    "/auth/google/callback",
    summary="Google OAuth2 callback — exchanges code for JWT",
    response_class=RedirectResponse,
)
def google_callback(code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    """
    OAuth2 callback from Google.
    Verifies state, exchanges code, finds or creates user.
    Redirects to frontend with access_token in query param.
    """
    user_info = sso_service.exchange_global_google_code(code, state)
    email: str = user_info["email"]

    domain = email.split("@")[-1]
    company = company_repository.get_by_domain(db, domain)
    company_id = company.id if company else None

    user = user_repository.find_or_create_sso_user(
        db, email=email, name=user_info.get("name"), company_id=company_id
    )
    user_repository.set_last_login(db, user.id)
    token = create_access_token(sub=user.id)

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    return RedirectResponse(f"{frontend_url}/?token={token}", status_code=302)


@router.put("/me", response_model=UserResponse, summary="Update the current user's profile")
@router.patch("/me", response_model=UserResponse, summary="Update the current user's profile (partial)")
def update_me(
    body: UpdateProfileRequest,
    current_user=Depends(user_service.get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Update mutable profile fields (name, department_name).

    Only fields included in the request body are written;
    omitted fields are left unchanged.

    - **401** if token is missing, invalid, or expired.
    """
    from app.repositories import user_repository

    if body.company_id is not None:
        if company_repository.get_by_id(db, body.company_id) is None:
            raise HTTPException(
                status_code=400,
                detail=f"company_id '{body.company_id}' does not exist",
            )

    updated = user_repository.update_profile(
        db,
        user_id=current_user.id,
        name=body.name,
        department_name=body.department_name,
        company_id=body.company_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return build_user_response(updated, db)
