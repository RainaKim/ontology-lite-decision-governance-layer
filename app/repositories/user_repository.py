"""
app/repositories/user_repository.py — Pure DB access for User records.

No password hashing, no JWT, no business logic.
All functions accept a SQLAlchemy Session and return ORM objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import User


def get_by_email(db: Session, email: str) -> Optional[User]:
    """Return the user with this email (lowercased) or None."""
    return db.query(User).filter(User.email == email.lower()).first()


def get_by_id(db: Session, user_id: str) -> Optional[User]:
    """Return the user with this ID or None."""
    return db.query(User).filter(User.id == user_id).first()


def get_by_email_and_company(
    db: Session, email: str, company_id: str
) -> Optional[User]:
    """Return a user matching email + company_id (used for SSO user lookup)."""
    return (
        db.query(User)
        .filter(User.email == email.lower(), User.company_id == company_id)
        .first()
    )


def create(
    db: Session,
    email: str,
    password_hash: Optional[str],
    name: Optional[str] = None,
    company_id: Optional[str] = None,
    role: str = "USER",
    department_name: Optional[str] = None,
) -> User:
    """
    Insert a new User row and return the persisted object.

    Caller is responsible for ensuring the email is not already taken.
    password_hash may be None for SSO users.
    """
    user = User(
        email=email.lower(),
        password_hash=password_hash,
        name=name,
        company_id=company_id,
        role=role,
        department_name=department_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_last_login(db: Session, user_id: str) -> None:
    """
    Update last_login_at to record the last login time.

    No-op if user_id is not found.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()


def update_profile(
    db: Session,
    user_id: str,
    name: Optional[str] = None,
    department_name: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Optional[User]:
    """
    Update mutable profile fields. Returns the updated User or None if not found.
    Only fields that are explicitly passed (not None) are written.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    if name is not None:
        user.name = name
    if department_name is not None:
        user.department_name = department_name
    if company_id is not None:
        user.company_id = company_id
    db.commit()
    db.refresh(user)
    return user


def find_or_create_sso_user(
    db: Session,
    email: str,
    name: Optional[str],
    company_id: Optional[str],
) -> User:
    """
    Find an existing user by email (any company), or create one with role=USER.

    Used in SSO callback handlers. The created user has no password_hash.
    If the user already exists, update company_id and name if they are now known.
    """
    user = get_by_email(db, email)
    if user:
        if company_id and not user.company_id:
            user.company_id = company_id
        if name and not user.name:
            user.name = name
        db.commit()
        db.refresh(user)
        return user
    return create(
        db,
        email=email,
        password_hash=None,
        name=name,
        company_id=company_id,
        role="USER",
    )
