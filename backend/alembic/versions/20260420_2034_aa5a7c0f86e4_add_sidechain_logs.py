"""add sidechain_logs table for agent architecture

Revision ID: aa5a7c0f86e4
Revises: 20260417_1340_b058866f8c43
Create Date: 2026-04-20 20:34:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "aa5a7c0f86e4"
down_revision: Union[str, None] = "b058866f8c43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sidechain_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("parent_session_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_sidechain_session",
        "sidechain_logs",
        ["session_id", "created_at"],
    )
    op.create_index(
        "idx_sidechain_parent",
        "sidechain_logs",
        ["parent_session_id", "agent_id"],
    )
    op.create_index(
        "idx_sidechain_event",
        "sidechain_logs",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_sidechain_event", table_name="sidechain_logs")
    op.drop_index("idx_sidechain_parent", table_name="sidechain_logs")
    op.drop_index("idx_sidechain_session", table_name="sidechain_logs")
    op.drop_table("sidechain_logs")
