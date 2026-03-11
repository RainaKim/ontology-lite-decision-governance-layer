"""
app/repositories/company_repository.py — Pure DB access for Company records.

No business logic. All functions accept a SQLAlchemy Session and return ORM objects.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.company import Company


def get_by_id(db: Session, company_id: str) -> Optional[Company]:
    """Return the company with this ID or None."""
    return db.query(Company).filter(Company.id == company_id).first()


def get_by_domain(db: Session, domain: str) -> Optional[Company]:
    """Return the company with this domain_url or None."""
    return db.query(Company).filter(Company.domain_url == domain).first()


def list_all(db: Session) -> list[Company]:
    """Return all active companies ordered by company_name."""
    return (
        db.query(Company)
        .filter(Company.status == "ACTIVE")
        .order_by(Company.company_name)
        .all()
    )


def create(
    db: Session,
    company_name: str,
    domain_url: str,
    license_tier: str = "BASIC",
    auth_type: str = "LOCAL",
    status: str = "ACTIVE",
    sso_client_id: Optional[str] = None,
    sso_client_secret: Optional[str] = None,
    sso_tenant_id: Optional[str] = None,
) -> Company:
    """
    Insert a new Company row and return the persisted object.

    Caller is responsible for ensuring domain_url is not already taken.
    """
    company = Company(
        company_name=company_name,
        domain_url=domain_url,
        license_tier=license_tier,
        auth_type=auth_type,
        status=status,
        sso_client_id=sso_client_id,
        sso_client_secret=sso_client_secret,
        sso_tenant_id=sso_tenant_id,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company
