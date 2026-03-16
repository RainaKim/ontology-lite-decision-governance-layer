"""
app/models/user.py — User ORM model.

id is a UUID stored as VARCHAR(36) for cross-database compatibility
(PostgreSQL and SQLite dev fallback).

password_hash is nullable to support SSO users who authenticate via OAuth2
and have no local password.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    # Primary key — UUID as string for cross-database compatibility
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Auth
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    # Nullable: SSO users have no local password
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Profile
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    department_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Company membership (nullable for users not yet linked to a DB company)
    company_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )

    # RBAC
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ADMIN"
    )  # ADMIN | MANAGER | USER

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} role={self.role!r}>"
