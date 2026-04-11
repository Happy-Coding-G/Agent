-- Trade bootstrap DDL generated from current SQLAlchemy models.
-- Source of truth: backend/app/db/models.py
BEGIN;

CREATE TYPE listing_status AS ENUM ('draft', 'active', 'paused', 'sold_out', 'delisted', 'suspended');

CREATE TYPE order_status AS ENUM ('pending', 'completed', 'cancelled', 'refunded', 'disputed');

CREATE TYPE yield_strategy AS ENUM ('conservative', 'balanced', 'aggressive');


CREATE TABLE trade_listings (
	id BIGSERIAL NOT NULL, 
	public_id VARCHAR(32) NOT NULL, 
	asset_id VARCHAR(32), 
	space_public_id VARCHAR(32), 
	seller_user_id BIGINT NOT NULL, 
	seller_alias VARCHAR(64) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	category VARCHAR(64) DEFAULT 'knowledge_report' NOT NULL, 
	tags VARCHAR(32)[] DEFAULT '{}' NOT NULL, 
	price_credits INTEGER NOT NULL, 
	public_summary TEXT, 
	preview_excerpt TEXT, 
	delivery_payload_encrypted BYTEA, 
	status listing_status DEFAULT 'draft' NOT NULL, 
	purchase_count INTEGER DEFAULT 0 NOT NULL, 
	market_view_count INTEGER DEFAULT 0 NOT NULL, 
	revenue_total BIGINT DEFAULT 0 NOT NULL, 
	auto_reprice_enabled BOOLEAN DEFAULT true NOT NULL, 
	last_reprice_at TIMESTAMP WITH TIME ZONE, 
	demand_score FLOAT DEFAULT 0 NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (public_id), 
	FOREIGN KEY(seller_user_id) REFERENCES users (id) ON DELETE CASCADE
)

;


CREATE TABLE trade_orders (
	id BIGSERIAL NOT NULL, 
	public_id VARCHAR(32) NOT NULL, 
	listing_id VARCHAR(32) NOT NULL, 
	buyer_user_id BIGINT NOT NULL, 
	seller_user_id BIGINT NOT NULL, 
	asset_title_snapshot VARCHAR(255) NOT NULL, 
	seller_alias_snapshot VARCHAR(64) NOT NULL, 
	price_credits INTEGER NOT NULL, 
	platform_fee INTEGER NOT NULL, 
	seller_income INTEGER NOT NULL, 
	delivery_payload_encrypted BYTEA, 
	status order_status DEFAULT 'pending' NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (public_id), 
	FOREIGN KEY(buyer_user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(seller_user_id) REFERENCES users (id) ON DELETE CASCADE
)

;


CREATE TABLE trade_wallets (
	id BIGSERIAL NOT NULL, 
	user_id BIGINT NOT NULL, 
	liquid_credits BIGINT DEFAULT 100000 NOT NULL, 
	cumulative_sales_earnings BIGINT DEFAULT 0 NOT NULL, 
	cumulative_yield_earnings BIGINT DEFAULT 0 NOT NULL, 
	total_spent BIGINT DEFAULT 0 NOT NULL, 
	auto_yield_enabled BOOLEAN DEFAULT true NOT NULL, 
	yield_strategy yield_strategy DEFAULT 'balanced' NOT NULL, 
	last_yield_run_at TIMESTAMP WITH TIME ZONE, 
	version INTEGER DEFAULT 1 NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)

;


CREATE TABLE trade_holdings (
	id BIGSERIAL NOT NULL, 
	user_id BIGINT NOT NULL, 
	order_id VARCHAR(32) NOT NULL, 
	listing_id VARCHAR(32) NOT NULL, 
	asset_title VARCHAR(255) NOT NULL, 
	seller_alias VARCHAR(64) NOT NULL, 
	access_expires_at TIMESTAMP WITH TIME ZONE, 
	download_count INTEGER DEFAULT 0 NOT NULL, 
	last_accessed_at TIMESTAMP WITH TIME ZONE, 
	purchased_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uk_holdings_user_listing UNIQUE (user_id, listing_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (order_id)
)

;


CREATE TABLE trade_yield_runs (
	id BIGSERIAL NOT NULL, 
	public_id VARCHAR(32) NOT NULL, 
	user_id BIGINT NOT NULL, 
	strategy yield_strategy NOT NULL, 
	annual_rate FLOAT NOT NULL, 
	elapsed_days FLOAT NOT NULL, 
	yield_amount BIGINT NOT NULL, 
	liquid_credits_before BIGINT NOT NULL, 
	liquid_credits_after BIGINT NOT NULL, 
	listing_adjustments JSONB DEFAULT '[]' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (public_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)

;


CREATE TABLE trade_transaction_log (
	id BIGSERIAL NOT NULL, 
	public_id VARCHAR(32) NOT NULL, 
	tx_type VARCHAR(32) NOT NULL, 
	user_id BIGINT NOT NULL, 
	order_id VARCHAR(32), 
	listing_id VARCHAR(32), 
	amount_delta BIGINT NOT NULL, 
	balance_before BIGINT NOT NULL, 
	balance_after BIGINT NOT NULL, 
	record_metadata JSONB, 
	ip_address VARCHAR(64), 
	user_agent TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (public_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)

;

CREATE INDEX idx_listings_category ON trade_listings (category);

CREATE INDEX idx_listings_created ON trade_listings (created_at);

CREATE INDEX idx_listings_price ON trade_listings (price_credits);

CREATE INDEX idx_listings_seller ON trade_listings (seller_user_id);

CREATE INDEX idx_listings_status ON trade_listings (status);

CREATE INDEX idx_orders_buyer ON trade_orders (buyer_user_id);

CREATE INDEX idx_orders_created ON trade_orders (created_at);

CREATE INDEX idx_orders_listing ON trade_orders (listing_id);

CREATE INDEX idx_orders_seller ON trade_orders (seller_user_id);

CREATE INDEX idx_orders_status ON trade_orders (status);

CREATE INDEX idx_wallets_user ON trade_wallets (user_id);

CREATE INDEX idx_holdings_listing ON trade_holdings (listing_id);

CREATE INDEX idx_holdings_user ON trade_holdings (user_id);

CREATE INDEX idx_yield_runs_created ON trade_yield_runs (created_at);

CREATE INDEX idx_yield_runs_user ON trade_yield_runs (user_id);

CREATE INDEX idx_tx_log_created ON trade_transaction_log (created_at);

CREATE INDEX idx_tx_log_type ON trade_transaction_log (tx_type);

CREATE INDEX idx_tx_log_user ON trade_transaction_log (user_id);

COMMIT;
