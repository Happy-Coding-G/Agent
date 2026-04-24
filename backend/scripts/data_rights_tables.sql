-- Data Rights Database Schema
-- Phase 1: Data Rights Tables
-- Run this SQL in your PostgreSQL database

-- ========================================================
-- 1. Create Enum Types
-- ========================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'data_sensitivity_level') THEN
        CREATE TYPE data_sensitivity_level AS ENUM ('low', 'medium', 'high', 'critical');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'computation_method') THEN
        CREATE TYPE computation_method AS ENUM (
            'federated_learning', 'mpc', 'trusted_execution_environment',
            'differential_privacy', 'raw_data'
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'data_rights_status') THEN
        CREATE TYPE data_rights_status AS ENUM (
            'pending', 'active', 'granted', 'expired', 'revoked', 'violated'
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audit_computation_method') THEN
        CREATE TYPE audit_computation_method AS ENUM (
            'federated_learning', 'mpc', 'trusted_execution_environment',
            'differential_privacy', 'raw_data'
        );
    END IF;
END $$;

-- ========================================================
-- 2. Create Data Assets Table
-- ========================================================

CREATE TABLE IF NOT EXISTS data_assets (
    id BIGSERIAL PRIMARY KEY,
    asset_id VARCHAR(64) UNIQUE NOT NULL,
    owner_id BIGINT NOT NULL REFERENCES users(id),
    asset_name VARCHAR(200) NOT NULL,
    asset_description TEXT,
    data_type VARCHAR(50) NOT NULL,
    sensitivity_level data_sensitivity_level NOT NULL,
    default_anonymization_level INTEGER DEFAULT 2,
    quality_completeness FLOAT DEFAULT 0.0,
    quality_accuracy FLOAT DEFAULT 0.0,
    quality_timeliness FLOAT DEFAULT 0.0,
    quality_consistency FLOAT DEFAULT 0.0,
    quality_uniqueness FLOAT DEFAULT 0.0,
    quality_overall_score FLOAT DEFAULT 0.0,
    raw_data_source VARCHAR(500) NOT NULL,
    lineage_root VARCHAR(64),
    processing_chain_hash VARCHAR(64),
    storage_location VARCHAR(500) NOT NULL,
    data_size_bytes BIGINT DEFAULT 0,
    record_count INTEGER,
    related_entities JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    is_available_for_trade BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for data_assets
CREATE INDEX IF NOT EXISTS ix_data_assets_owner ON data_assets(owner_id);
CREATE INDEX IF NOT EXISTS ix_data_assets_sensitivity ON data_assets(sensitivity_level);
CREATE INDEX IF NOT EXISTS ix_data_assets_type ON data_assets(data_type);
CREATE INDEX IF NOT EXISTS ix_data_assets_quality ON data_assets(quality_overall_score);

-- ========================================================
-- 3. Create Data Rights Transactions Table
-- ========================================================

CREATE TABLE IF NOT EXISTS data_rights_transactions (
    id BIGSERIAL PRIMARY KEY,
    transaction_id VARCHAR(64) UNIQUE NOT NULL,
    negotiation_id VARCHAR(64) REFERENCES negotiation_sessions(negotiation_id),
    data_asset_id VARCHAR(64) NOT NULL REFERENCES data_assets(asset_id),
    owner_id BIGINT NOT NULL REFERENCES users(id),
    buyer_id BIGINT NOT NULL REFERENCES users(id),
    rights_types JSONB NOT NULL,
    usage_scope JSONB NOT NULL,
    restrictions JSONB DEFAULT '[]',
    computation_method computation_method NOT NULL,
    anonymization_level INTEGER NOT NULL,
    computation_constraints JSONB DEFAULT '{}',
    valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
    valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
    agreed_price FLOAT,
    currency VARCHAR(10) DEFAULT 'CNY',
    status data_rights_status DEFAULT 'pending',
    settlement_tx_hash VARCHAR(128),
    settlement_time TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for data_rights_transactions
CREATE INDEX IF NOT EXISTS ix_rights_tx_asset ON data_rights_transactions(data_asset_id);
CREATE INDEX IF NOT EXISTS ix_rights_tx_owner ON data_rights_transactions(owner_id);
CREATE INDEX IF NOT EXISTS ix_rights_tx_buyer ON data_rights_transactions(buyer_id);
CREATE INDEX IF NOT EXISTS ix_rights_tx_status ON data_rights_transactions(status);
CREATE INDEX IF NOT EXISTS ix_rights_tx_validity ON data_rights_transactions(valid_from, valid_until);

-- ========================================================
-- 4. Create Data Access Audit Logs Table
-- ========================================================

CREATE TABLE IF NOT EXISTS data_access_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    log_id VARCHAR(64) UNIQUE NOT NULL,
    transaction_id VARCHAR(64) NOT NULL REFERENCES data_rights_transactions(transaction_id),
    negotiation_id VARCHAR(64),
    data_asset_id VARCHAR(64) NOT NULL,
    buyer_id BIGINT NOT NULL REFERENCES users(id),
    access_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    access_purpose VARCHAR(200) NOT NULL,
    computation_method_used audit_computation_method NOT NULL,
    query_fingerprint VARCHAR(64) NOT NULL,
    query_complexity_score FLOAT,
    result_size_bytes BIGINT DEFAULT 0,
    result_row_count INTEGER,
    result_aggregation_level VARCHAR(50) NOT NULL,
    policy_compliance_check JSONB DEFAULT '{}',
    risk_score FLOAT,
    anomaly_flags JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for data_access_audit_logs
CREATE INDEX IF NOT EXISTS ix_audit_tx ON data_access_audit_logs(transaction_id);
CREATE INDEX IF NOT EXISTS ix_audit_buyer ON data_access_audit_logs(buyer_id);
CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON data_access_audit_logs(access_timestamp);
CREATE INDEX IF NOT EXISTS ix_audit_risk ON data_access_audit_logs(risk_score);

-- ========================================================
-- 5. Create Policy Violations Table
-- ========================================================

CREATE TABLE IF NOT EXISTS policy_violations (
    id BIGSERIAL PRIMARY KEY,
    violation_id VARCHAR(64) UNIQUE NOT NULL,
    transaction_id VARCHAR(64) NOT NULL REFERENCES data_rights_transactions(transaction_id),
    negotiation_id VARCHAR(64),
    data_asset_id VARCHAR(64) NOT NULL,
    violation_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    violation_details JSONB NOT NULL,
    evidence JSONB NOT NULL,
    potential_data_exposure FLOAT,
    affected_records_estimate INTEGER,
    automatic_action_taken VARCHAR(200),
    manual_review_status VARCHAR(50) DEFAULT 'pending',
    resolution_notes TEXT,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for policy_violations
CREATE INDEX IF NOT EXISTS ix_violation_tx ON policy_violations(transaction_id);
CREATE INDEX IF NOT EXISTS ix_violation_type ON policy_violations(violation_type);
CREATE INDEX IF NOT EXISTS ix_violation_severity ON policy_violations(severity);
CREATE INDEX IF NOT EXISTS ix_violation_status ON policy_violations(manual_review_status);

-- ========================================================
-- 6. Verification Query
-- ========================================================

SELECT 'Tables created successfully' as status;

SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
AND table_name IN (
    'data_assets',
    'data_rights_transactions',
    'data_access_audit_logs',
    'policy_violations'
)
ORDER BY table_name;
