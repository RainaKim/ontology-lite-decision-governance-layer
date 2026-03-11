"""decisions: add bilingual fields (agent_name_en, department_en, proposed_text_en)

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("decisions", sa.Column("agent_name_en", sa.String(200), nullable=True))
    op.add_column("decisions", sa.Column("department_en", sa.String(100), nullable=True))
    op.add_column("decisions", sa.Column("proposed_text_en", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("decisions", "proposed_text_en")
    op.drop_column("decisions", "department_en")
    op.drop_column("decisions", "agent_name_en")
