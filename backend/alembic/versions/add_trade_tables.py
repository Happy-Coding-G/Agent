"""
数据库迁移脚本：创建 Trade 相关表
执行: alembic revision -m "add_trade_tables"
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_trade_tables'
down_revision = None  # 根据实际调整
branch_labels = None
depends_on = None


def upgrade():
    # 创建枚举类型
    listing_status = postgresql.ENUM(
        'draft', 'active', 'paused', 'sold_out', 'delisted', 'suspended',
        name='listing_status'
    )
    listing_status.create(op.get_bind())

    order_status = postgresql.ENUM(
        'pending', 'completed', 'cancelled', 'refunded', 'disputed',
        name='order_status'
    )
    order_status.create(op.get_bind())

    yield_strategy = postgresql.ENUM(
        'conservative', 'balanced', 'aggressive',
        name='yield_strategy'
    )
    yield_strategy.create(op.get_bind())

    # ==========================================================================
    # 1. 数字资产列表 (Listings)
    # ==========================================================================
    op.create_table(
        'trade_listings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('public_id', sa.String(32), nullable=False, unique=True),
        sa.Column('asset_id', sa.String(32), nullable=True),  # 关联本地资产
        sa.Column('space_public_id', sa.String(32), nullable=True),

        # 卖家信息
        sa.Column('seller_user_id', sa.BigInteger(), nullable=False),
        sa.Column('seller_alias', sa.String(64), nullable=False),

        # 资产内容
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String(32)), server_default='{}'),

        # 价格 (使用整数存储避免浮点误差，单位：分/积分最小单位)
        sa.Column('price_credits', sa.Integer(), nullable=False),  # 实际金额 = price_credits / 100

        # 公开信息 (购买前可见)
        sa.Column('public_summary', sa.Text()),
        sa.Column('preview_excerpt', sa.Text()),

        # 交付内容 (购买后可见，存储在独立表或加密字段)
        sa.Column('delivery_payload_encrypted', sa.LargeBinary()),

        # 状态
        sa.Column('status', postgresql.ENUM(
            'draft', 'active', 'paused', 'sold_out', 'delisted', 'suspended',
            name='listing_status'
        ), server_default='draft'),

        # 统计
        sa.Column('purchase_count', sa.Integer(), server_default='0'),
        sa.Column('market_view_count', sa.Integer(), server_default='0'),
        sa.Column('revenue_total', sa.BigInteger(), server_default='0'),  # 整数存储

        # 自动调价相关
        sa.Column('auto_reprice_enabled', sa.Boolean(), server_default='true'),
        sa.Column('last_reprice_at', sa.DateTime(timezone=True)),
        sa.Column('demand_score', sa.Float(), server_default='0'),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['seller_user_id'], ['users.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_listings_status', 'trade_listings', ['status'])
    op.create_index('idx_listings_seller', 'trade_listings', ['seller_user_id'])
    op.create_index('idx_listings_category', 'trade_listings', ['category'])
    op.create_index('idx_listings_price', 'trade_listings', ['price_credits'])
    op.create_index('idx_listings_created', 'trade_listings', ['created_at'])

    # ==========================================================================
    # 2. 订单 (Orders)
    # ==========================================================================
    op.create_table(
        'trade_orders',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('public_id', sa.String(32), nullable=False, unique=True),

        # 关联
        sa.Column('listing_id', sa.String(32), nullable=False),
        sa.Column('buyer_user_id', sa.BigInteger(), nullable=False),
        sa.Column('seller_user_id', sa.BigInteger(), nullable=False),

        # 快照 (购买时的 listing 信息)
        sa.Column('asset_title_snapshot', sa.String(255), nullable=False),
        sa.Column('seller_alias_snapshot', sa.String(64), nullable=False),

        # 金额 (整数存储)
        sa.Column('price_credits', sa.Integer(), nullable=False),
        sa.Column('platform_fee', sa.Integer(), nullable=False),
        sa.Column('seller_income', sa.Integer(), nullable=False),

        # 交付内容快照
        sa.Column('delivery_payload_encrypted', sa.LargeBinary()),

        # 状态
        sa.Column('status', postgresql.ENUM(
            'pending', 'completed', 'cancelled', 'refunded', 'disputed',
            name='order_status'
        ), server_default='pending'),

        # 时间
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['buyer_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['seller_user_id'], ['users.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_orders_buyer', 'trade_orders', ['buyer_user_id'])
    op.create_index('idx_orders_seller', 'trade_orders', ['seller_user_id'])
    op.create_index('idx_orders_listing', 'trade_orders', ['listing_id'])
    op.create_index('idx_orders_status', 'trade_orders', ['status'])
    op.create_index('idx_orders_created', 'trade_orders', ['created_at'])

    # ==========================================================================
    # 3. 用户钱包 (Wallets) - 使用乐观锁或行级锁
    # ==========================================================================
    op.create_table(
        'trade_wallets',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False, unique=True),

        # 余额 (整数存储，避免浮点误差)
        sa.Column('liquid_credits', sa.BigInteger(), server_default='100000'),  # 默认 1000.00
        sa.Column('cumulative_sales_earnings', sa.BigInteger(), server_default='0'),
        sa.Column('cumulative_yield_earnings', sa.BigInteger(), server_default='0'),
        sa.Column('total_spent', sa.BigInteger(), server_default='0'),

        # 收益设置
        sa.Column('auto_yield_enabled', sa.Boolean(), server_default='true'),
        sa.Column('yield_strategy', postgresql.ENUM(
            'conservative', 'balanced', 'aggressive',
            name='yield_strategy'
        ), server_default='balanced'),
        sa.Column('last_yield_run_at', sa.DateTime(timezone=True)),

        # 版本号 (乐观锁)
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_wallets_user', 'trade_wallets', ['user_id'])
    op.create_index('idx_wallets_version', 'trade_wallets', ['version'])

    # ==========================================================================
    # 4. 用户持仓 (Holdings) - 已购买的资产
    # ==========================================================================
    op.create_table(
        'trade_holdings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.String(32), nullable=False, unique=True),
        sa.Column('listing_id', sa.String(32), nullable=False),

        # 快照信息
        sa.Column('asset_title', sa.String(255), nullable=False),
        sa.Column('seller_alias', sa.String(64), nullable=False),

        # 访问控制
        sa.Column('access_expires_at', sa.DateTime(timezone=True)),  # 可选的订阅制过期时间
        sa.Column('download_count', sa.Integer(), server_default='0'),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True)),

        sa.Column('purchased_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'listing_id', name='uk_holdings_user_listing'),
    )

    op.create_index('idx_holdings_user', 'trade_holdings', ['user_id'])
    op.create_index('idx_holdings_listing', 'trade_holdings', ['listing_id'])

    # ==========================================================================
    # 5. 收益运行日志 (Yield Runs)
    # ==========================================================================
    op.create_table(
        'trade_yield_runs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('public_id', sa.String(32), nullable=False, unique=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),

        # 运行参数
        sa.Column('strategy', postgresql.ENUM(
            'conservative', 'balanced', 'aggressive',
            name='yield_strategy'
        ), nullable=False),
        sa.Column('annual_rate', sa.Float(), nullable=False),
        sa.Column('elapsed_days', sa.Float(), nullable=False),

        # 收益金额 (整数)
        sa.Column('yield_amount', sa.BigInteger(), nullable=False),

        # 钱包快照
        sa.Column('liquid_credits_before', sa.BigInteger(), nullable=False),
        sa.Column('liquid_credits_after', sa.BigInteger(), nullable=False),

        # 关联的调价记录 (JSONB)
        sa.Column('listing_adjustments', postgresql.JSONB(), server_default='[]'),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_yield_runs_user', 'trade_yield_runs', ['user_id'])
    op.create_index('idx_yield_runs_created', 'trade_yield_runs', ['created_at'])

    # ==========================================================================
    # 6. 交易审计日志 (Transaction Log) - 用于审计和对账
    # ==========================================================================
    op.create_table(
        'trade_transaction_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('public_id', sa.String(32), nullable=False, unique=True),

        # 交易类型
        sa.Column('tx_type', sa.String(32), nullable=False),  # deposit, purchase, sale_yield, yield_accrual, refund

        # 关联
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.String(32), nullable=True),
        sa.Column('listing_id', sa.String(32), nullable=True),

        # 金额变化 (整数)
        sa.Column('amount_delta', sa.BigInteger(), nullable=False),
        sa.Column('balance_before', sa.BigInteger(), nullable=False),
        sa.Column('balance_after', sa.BigInteger(), nullable=False),

        # 元数据
        sa.Column('metadata', postgresql.JSONB()),
        sa.Column('ip_address', sa.String(64)),
        sa.Column('user_agent', sa.Text()),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_tx_log_user', 'trade_transaction_log', ['user_id'])
    op.create_index('idx_tx_log_type', 'trade_transaction_log', ['tx_type'])
    op.create_index('idx_tx_log_created', 'trade_transaction_log', ['created_at'])

    # ==========================================================================
    # 7. 添加用户初始钱包触发器
    # ==========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION create_user_wallet()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO trade_wallets (user_id, liquid_credits)
            VALUES (NEW.id, 100000)  -- 默认 1000.00 积分
            ON CONFLICT (user_id) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trigger_create_user_wallet
        AFTER INSERT ON users
        FOR EACH ROW
        EXECUTE FUNCTION create_user_wallet();
    """)


def downgrade():
    # 删除触发器
    op.execute("DROP TRIGGER IF EXISTS trigger_create_user_wallet ON users")
    op.execute("DROP FUNCTION IF EXISTS create_user_wallet()")

    # 删除表
    op.drop_table('trade_transaction_log')
    op.drop_table('trade_yield_runs')
    op.drop_table('trade_holdings')
    op.drop_table('trade_wallets')
    op.drop_table('trade_orders')
    op.drop_table('trade_listings')

    # 删除枚举
    op.execute("DROP TYPE IF EXISTS listing_status")
    op.execute("DROP TYPE IF EXISTS order_status")
    op.execute("DROP TYPE IF EXISTS yield_strategy")
