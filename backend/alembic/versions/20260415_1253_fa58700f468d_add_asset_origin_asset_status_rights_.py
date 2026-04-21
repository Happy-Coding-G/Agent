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
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if 'data_assets' in tables:
        existing_columns = {column['name'] for column in inspector.get_columns('data_assets')}
        if 'asset_origin' not in existing_columns:
            op.add_column(
                'data_assets',
                sa.Column('asset_origin', sa.String(length=32), server_default=sa.text("'space_generated'"), nullable=True)
            )
        if 'asset_status' not in existing_columns:
            op.add_column(
                'data_assets',
                sa.Column('asset_status', sa.String(length=32), server_default=sa.text("'draft'"), nullable=True)
            )

    if 'trade_listings' in tables:
        existing_columns = {column['name'] for column in inspector.get_columns('trade_listings')}
        if 'rights_template' not in existing_columns:
            op.add_column(
                'trade_listings',
                sa.Column('rights_template', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False)
            )

    if 'data_rights_transactions' in tables:
        existing_columns = {column['name'] for column in inspector.get_columns('data_rights_transactions')}
        if 'listing_id' not in existing_columns:
            op.add_column(
                'data_rights_transactions',
                sa.Column('listing_id', sa.String(length=64), nullable=True)
            )
        if 'order_id' not in existing_columns:
            op.add_column(
                'data_rights_transactions',
                sa.Column('order_id', sa.String(length=64), nullable=True)
            )

        refreshed_columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('data_rights_transactions')}
        if 'listing_id' in refreshed_columns:
            op.create_index(
                op.f('ix_data_rights_transactions_listing_id'), 'data_rights_transactions', ['listing_id'], unique=False, if_not_exists=True
            )
        if 'order_id' in refreshed_columns:
            op.create_index(
                op.f('ix_data_rights_transactions_order_id'), 'data_rights_transactions', ['order_id'], unique=False, if_not_exists=True
            )


def downgrade() -> None:
    op.drop_index(op.f('ix_data_rights_transactions_order_id'), table_name='data_rights_transactions', if_exists=True)
    op.drop_index(op.f('ix_data_rights_transactions_listing_id'), table_name='data_rights_transactions', if_exists=True)
    op.execute("ALTER TABLE IF EXISTS data_rights_transactions DROP COLUMN IF EXISTS order_id")
    op.execute("ALTER TABLE IF EXISTS data_rights_transactions DROP COLUMN IF EXISTS listing_id")
    op.execute("ALTER TABLE IF EXISTS trade_listings DROP COLUMN IF EXISTS rights_template")
    op.execute("ALTER TABLE IF EXISTS data_assets DROP COLUMN IF EXISTS asset_status")
    op.execute("ALTER TABLE IF EXISTS data_assets DROP COLUMN IF EXISTS asset_origin")
