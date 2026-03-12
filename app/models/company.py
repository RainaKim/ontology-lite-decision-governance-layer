"""
app/models/company.py — Company ORM model.

id is a UUID stored as VARCHAR(36) for cross-database compatibility.
SSO credentials (sso_client_secret) are stored but never returned in API responses.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    # Primary key — UUID as string for cross-database compatibility
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Identity
    company_name: Mapped[str] = mapped_column(String(100), nullable=False)
    company_name_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    domain_url: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Tier / status
    license_tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default="BASIC"
    )  # BASIC | PRO | ENTERPRISE
    auth_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="LOCAL"
    )  # LOCAL | GOOGLE_SSO | AZURE_SSO | SAML
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE"
    )  # ACTIVE | SUSPENDED | DELETED

    # SSO credentials — nullable; only populated for SSO companies
    sso_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sso_client_secret: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )  # sensitive — never returned in API responses
    sso_tenant_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Azure AD tenant_id

    # Timestamps
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
        return f"<Company id={self.id!r} name={self.company_name!r} auth={self.auth_type!r}>"
