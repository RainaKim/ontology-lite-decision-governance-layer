"""create agents table and add agent_id FK to decisions

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-13 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # ── Create agents table (idempotent — handles partial previous run) ──
    if "agents" not in existing_tables:
        op.create_table(
            "agents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "company_id",
                sa.String(36),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("name_en", sa.String(200), nullable=True),
            sa.Column("department", sa.String(100), nullable=False),
            sa.Column("department_en", sa.String(100), nullable=True),
            sa.Column(
                "autonomy",
                sa.String(20),
                nullable=False,
                server_default="Policy Bound",
            ),
            sa.Column("risk_threshold", sa.Integer, nullable=False, server_default="70"),
            sa.Column("financial_limit", sa.Numeric(precision=15, scale=2), nullable=True),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="Active"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    # Create indexes (idempotent — SQLite ignores IF NOT EXISTS via execute)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("agents")} if "agents" in inspector.get_table_names() else set()
    if "ix_agents_company_id" not in existing_indexes:
        op.create_index("ix_agents_company_id", "agents", ["company_id"])
    if "ix_agents_status" not in existing_indexes:
        op.create_index("ix_agents_status", "agents", ["status"])

    # ── Add agent_id FK to decisions (batch mode for SQLite) ────────────────
    decision_cols = {c["name"] for c in inspector.get_columns("decisions")}
    if "agent_id" not in decision_cols:
        with op.batch_alter_table("decisions") as batch_op:
            batch_op.add_column(
                sa.Column("agent_id", sa.String(36), nullable=True),
            )
            batch_op.create_foreign_key(
                "fk_decisions_agent_id",
                "agents",
                ["agent_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index("ix_decisions_agent_id", ["agent_id"])


def downgrade() -> None:
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_index("ix_decisions_agent_id")
        batch_op.drop_constraint("fk_decisions_agent_id", type_="foreignkey")
        batch_op.drop_column("agent_id")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_company_id", table_name="agents")
    op.drop_table("agents")
