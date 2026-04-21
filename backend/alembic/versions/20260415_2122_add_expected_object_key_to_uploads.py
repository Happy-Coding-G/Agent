"""add expected_object_key to uploads

Revision ID: 20260415_2122
Revises: fa58700f468d
Create Date: 2026-04-15 21:22:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260415_2122'
down_revision: Union[str, None] = 'fa58700f468d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS uploads ADD COLUMN IF NOT EXISTS expected_object_key VARCHAR(512)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS uploads DROP COLUMN IF EXISTS expected_object_key"
    )
