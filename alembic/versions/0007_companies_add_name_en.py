"""companies: add company_name_en

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("company_name_en", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "company_name_en")
