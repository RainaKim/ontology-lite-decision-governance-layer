"""create decisions table

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=True, index=True),
        sa.Column("agent_name", sa.String(200), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("proposed_text", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.75"),
        sa.Column("risk_level", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("impact_label", sa.String(50), nullable=True),
        sa.Column("contract_value", sa.BigInteger, nullable=True),
        sa.Column("affected_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"])
    op.create_index("ix_decisions_created_at", "decisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decisions_created_at", table_name="decisions")
    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_table("decisions")
