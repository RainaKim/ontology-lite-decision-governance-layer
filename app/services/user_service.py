"""
app/services/user_service.py — User signup, login, and auth dependency.

Depends on:
  app.repositories.user_repository  — DB access
  app.services.auth_service         — hashing + JWT
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.repositories import user_repository
from app.services import auth_service
from app.schemas.auth_responses import UserResponse

# HTTPBearer extracts "Authorization: Bearer <token>" from the request.
_bearer = HTTPBearer()


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


def signup(
    db: Session,
    email: str,
    password: str,
    name: str | None = None,
    role: str = "USER",
) -> User:
    """
    Create a new user account.

    Raises:
        HTTPException 409 — email already in use.
    """
    email = email.strip().lower()
    if user_repository.get_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    password_hash = auth_service.hash_password(password)
    return user_repository.create(db, email=email, password_hash=password_hash, name=name, role=role)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def login(
    db: Session,
    email: str,
    password: str,
) -> tuple[str, User]:
    """
    Verify credentials and return (access_token, user).

    Raises:
        HTTPException 401 — invalid email or password.
    """
    email = email.strip().lower()
    user = user_repository.get_by_email(db, email)
    if not user or not user.password_hash or not auth_service.verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )
    user_repository.set_last_login(db, user.id)
    token = auth_service.create_access_token(sub=user.id)
    return token, user


# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — extract Bearer token, decode it, return the User.

    Raises:
        HTTPException 401 — missing / invalid / expired token.
        HTTPException 403 — account inactive.
    """
    token = credentials.credentials
    payload = auth_service.decode_token(token)

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = user_repository.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )
    return user


# ---------------------------------------------------------------------------
# UserResponse builder (enriches with company info + permissions)
# ---------------------------------------------------------------------------


def build_user_response(user: User, db: Session) -> UserResponse:
    """
    Build a fully-populated UserResponse for a User ORM object.

    Performs a single company lookup when user.company_id is set;
    derives permissions from user.role via the RBAC config table.
    """
    from app.repositories import company_repository
    from app.services.rbac_service import get_permissions

    company_name: str | None = None
    license_tier: str | None = None
    auth_method: str | None = None

    if user.company_id:
        company = company_repository.get_by_id(db, user.company_id)
        if company:
            company_name = company.company_name
            license_tier = company.license_tier
            auth_method = company.auth_type

    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        department_name=user.department_name,
        company_id=user.company_id,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        company_name=company_name,
        license_tier=license_tier,
        auth_method=auth_method,
        permissions=get_permissions(user.role),
    )
