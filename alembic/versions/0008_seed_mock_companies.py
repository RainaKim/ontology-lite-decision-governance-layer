"""Seed mock companies into companies table.

Uses governance keys as PKs (nexus_dynamics, mayo_central, sool_sool_icecream)
so no UUID translation is needed when loading governance context from JSON.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-11 00:00:00.000000
"""

from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = datetime(2026, 3, 11, 0, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)

_COMPANIES = [
    {
        "id": "nexus_dynamics",
        "company_name": "넥서스 다이나믹스",
        "company_name_en": "Nexus Dynamics",
        "domain_url": "nexus-dynamics.governance.internal",
        "license_tier": "ENTERPRISE",
        "auth_type": "LOCAL",
        "status": "ACTIVE",
    },
    {
        "id": "mayo_central",
        "company_name": "Mayo Central Hospital",
        "company_name_en": "Mayo Central Hospital",
        "domain_url": "mayo-central.governance.internal",
        "license_tier": "ENTERPRISE",
        "auth_type": "LOCAL",
        "status": "ACTIVE",
    },
    {
        "id": "sool_sool_icecream",
        "company_name": "Sool Sool Ice Cream",
        "company_name_en": "Sool Sool Ice Cream",
        "domain_url": "sool-sool.governance.internal",
        "license_tier": "BASIC",
        "auth_type": "LOCAL",
        "status": "ACTIVE",
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for c in _COMPANIES:
        if dialect == "postgresql":
            bind.execute(
                sa.text(
                    """
                    INSERT INTO companies
                        (id, company_name, company_name_en, domain_url,
                         license_tier, auth_type, status, created_at, updated_at)
                    VALUES
                        (:id, :company_name, :company_name_en, :domain_url,
                         :license_tier, :auth_type, :status, :created_at, :updated_at)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {**c, "created_at": _NOW, "updated_at": _NOW},
            )
        else:
            bind.execute(
                sa.text(
                    """
                    INSERT OR IGNORE INTO companies
                        (id, company_name, company_name_en, domain_url,
                         license_tier, auth_type, status, created_at, updated_at)
                    VALUES
                        (:id, :company_name, :company_name_en, :domain_url,
                         :license_tier, :auth_type, :status, :created_at, :updated_at)
                    """
                ),
                {**c, "created_at": _NOW, "updated_at": _NOW},
            )


def downgrade() -> None:
    bind = op.get_bind()
    ids = [c["id"] for c in _COMPANIES]
    for company_id in ids:
        bind.execute(
            sa.text("DELETE FROM companies WHERE id = :id"),
            {"id": company_id},
        )
