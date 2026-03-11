"""update users table — add company_id, department_name, role, last_login_at; password_hash nullable

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-05 00:02:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not support ADD COLUMN with FK constraints or ALTER COLUMN.
    # Use batch mode (copy-and-move) for all changes on the users table.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("company_id", sa.String(36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("department_name", sa.String(100), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "role",
                sa.String(20),
                nullable=False,
                server_default="USER",
            )
        )
        batch_op.add_column(
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
        )
        # Make password_hash nullable (SSO users have no password)
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(255),
            nullable=True,
        )
        # Add FK constraint for company_id in batch mode
        batch_op.create_foreign_key(
            "fk_users_company_id",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_company_id", type_="foreignkey")
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(255),
            nullable=False,
        )
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("role")
        batch_op.drop_column("department_name")
        batch_op.drop_column("company_id")
