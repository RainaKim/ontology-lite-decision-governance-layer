"""create companies table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-05 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("company_name", sa.String(100), nullable=False),
        sa.Column("domain_url", sa.String(255), nullable=False),
        sa.Column(
            "license_tier",
            sa.String(20),
            nullable=False,
            server_default="BASIC",
        ),
        sa.Column(
            "auth_type",
            sa.String(20),
            nullable=False,
            server_default="LOCAL",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("sso_client_id", sa.String(255), nullable=True),
        sa.Column("sso_client_secret", sa.String(512), nullable=True),
        sa.Column("sso_tenant_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_url", name="uq_companies_domain_url"),
    )


def downgrade() -> None:
    op.drop_table("companies")
