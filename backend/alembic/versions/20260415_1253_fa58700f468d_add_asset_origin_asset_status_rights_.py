"""Add asset_origin, asset_status, rights_template, and rights tx listing/order ids

Revision ID: fa58700f468d
Revises: 004
Create Date: 2026-04-15 12:53:42.088723+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fa58700f468d'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # data_assets: add asset_origin and asset_status
    op.add_column(
        'data_assets',
        sa.Column('asset_origin', sa.String(length=32), server_default=sa.text("'space_generated'"), nullable=True)
    )
    op.add_column(
        'data_assets',
        sa.Column('asset_status', sa.String(length=32), server_default=sa.text("'draft'"), nullable=True)
    )

    # trade_listings: add rights_template snapshot
    op.add_column(
        'trade_listings',
        sa.Column('rights_template', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False)
    )

    # data_rights_transactions: add listing_id and order_id
    op.add_column(
        'data_rights_transactions',
        sa.Column('listing_id', sa.String(length=64), nullable=True)
    )
    op.add_column(
        'data_rights_transactions',
        sa.Column('order_id', sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f('ix_data_rights_transactions_listing_id'), 'data_rights_transactions', ['listing_id'], unique=False, if_not_exists=True
    )
    op.create_index(
        op.f('ix_data_rights_transactions_order_id'), 'data_rights_transactions', ['order_id'], unique=False, if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_data_rights_transactions_order_id'), table_name='data_rights_transactions', if_exists=True)
    op.drop_index(op.f('ix_data_rights_transactions_listing_id'), table_name='data_rights_transactions', if_exists=True)
    op.drop_column('data_rights_transactions', 'order_id')
    op.drop_column('data_rights_transactions', 'listing_id')
    op.drop_column('trade_listings', 'rights_template')
    op.drop_column('data_assets', 'asset_status')
    op.drop_column('data_assets', 'asset_origin')
