"""Seed agents table and backfill agent_id on existing decisions.

Uses fixed UUIDs so the migration is idempotent.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-13 12:00:00.000000
"""

from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = datetime.now(timezone.utc).replace(tzinfo=None)

_AGENTS = [
    # ── nexus_dynamics ────────────────────────────────────────────
    {
        "id": "agt-nexus-0001-marketing",
        "company_id": "nexus_dynamics",
        "name": "마케팅 AI Agent",
        "name_en": "Marketing AI Agent",
        "department": "마케팅팀",
        "department_en": "Marketing",
        "autonomy": "Policy Bound",
        "risk_threshold": 70,
        "financial_limit": 100000.00,
        "status": "Active",
    },
    {
        "id": "agt-nexus-0002-hr",
        "company_id": "nexus_dynamics",
        "name": "인사 AI Agent",
        "name_en": "HR AI Agent",
        "department": "인사팀",
        "department_en": "Human Resources",
        "autonomy": "Human Controlled",
        "risk_threshold": 50,
        "financial_limit": 50000.00,
        "status": "Active",
    },
    # ── mayo_central ──────────────────────────────────────────────
    {
        "id": "agt-mayo-0001-clinical",
        "company_id": "mayo_central",
        "name": "Clinical Data Agent",
        "name_en": "Clinical Data Agent",
        "department": "임상관리",
        "department_en": "Clinical Management",
        "autonomy": "Policy Bound",
        "risk_threshold": 60,
        "financial_limit": None,
        "status": "Active",
    },
    {
        "id": "agt-mayo-0002-infosec",
        "company_id": "mayo_central",
        "name": "정보보호 AI Agent",
        "name_en": "Information Security AI Agent",
        "department": "정보보호",
        "department_en": "Information Security",
        "autonomy": "Conditional",
        "risk_threshold": 65,
        "financial_limit": None,
        "status": "Active",
    },
]

# Map (company_id, agent_name) → agent id for backfill
_AGENT_LOOKUP = {(a["company_id"], a["name"]): a["id"] for a in _AGENTS}


def upgrade() -> None:
    bind = op.get_bind()
    agents_table = sa.table(
        "agents",
        sa.column("id", sa.String),
        sa.column("company_id", sa.String),
        sa.column("name", sa.String),
        sa.column("name_en", sa.String),
        sa.column("department", sa.String),
        sa.column("department_en", sa.String),
        sa.column("autonomy", sa.String),
        sa.column("risk_threshold", sa.Integer),
        sa.column("financial_limit", sa.Numeric),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    # Insert agents (skip if already present — idempotent)
    existing = {
        row[0]
        for row in bind.execute(sa.text("SELECT id FROM agents")).fetchall()
    }
    for agent in _AGENTS:
        if agent["id"] in existing:
            continue
        op.execute(
            agents_table.insert().values(
                id=agent["id"],
                company_id=agent["company_id"],
                name=agent["name"],
                name_en=agent["name_en"],
                department=agent["department"],
                department_en=agent["department_en"],
                autonomy=agent["autonomy"],
                risk_threshold=agent["risk_threshold"],
                financial_limit=agent["financial_limit"],
                status=agent["status"],
                created_at=_NOW,
                updated_at=_NOW,
            )
        )

    # Backfill agent_id on decisions that don't have one yet
    decisions = bind.execute(
        sa.text("SELECT id, company_id, agent_name FROM decisions WHERE agent_id IS NULL")
    ).fetchall()
    for dec_id, company_id, agent_name in decisions:
        agent_id = _AGENT_LOOKUP.get((company_id, agent_name))
        if agent_id:
            bind.execute(
                sa.text("UPDATE decisions SET agent_id = :aid WHERE id = :did"),
                {"aid": agent_id, "did": dec_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    # Clear agent_id from decisions
    bind.execute(sa.text("UPDATE decisions SET agent_id = NULL"))
    # Remove seeded agents
    for agent in _AGENTS:
        bind.execute(
            sa.text("DELETE FROM agents WHERE id = :id"),
            {"id": agent["id"]},
        )
