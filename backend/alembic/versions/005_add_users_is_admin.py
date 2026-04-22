"""add is_admin to users

Revision ID: 005_add_users_is_admin
Revises: 20260420_2034_aa5a7c0f86e4_add_sidechain_logs
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "005_add_users_is_admin"
down_revision = "20260420_2034_aa5a7c0f86e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
