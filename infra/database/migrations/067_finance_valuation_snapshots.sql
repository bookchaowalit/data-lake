-- Finance valuation snapshot contract.
-- These tables store normalized snapshot/control metadata only. They do not
-- store raw provider payloads, credentials, or trading instructions.

CREATE TABLE IF NOT EXISTS finance_market_price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_key TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    as_of TEXT NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('exchange', 'broker', 'custodian', 'manual', 'derived')),
    quality TEXT NOT NULL DEFAULT 'provisional'
        CHECK (quality IN ('verified', 'provisional', 'stale', 'rejected')),
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_ref TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(instrument_key)) BETWEEN 1 AND 160),
    CHECK (length(trim(currency)) BETWEEN 3 AND 12),
    UNIQUE(instrument_key, as_of, source_type)
);

CREATE TABLE IF NOT EXISTS finance_valuation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investment_id INTEGER NOT NULL REFERENCES finance_investments(id) ON DELETE CASCADE,
    market_price_snapshot_id INTEGER REFERENCES finance_market_price_snapshots(id) ON DELETE SET NULL,
    quantity REAL CHECK (quantity IS NULL OR quantity >= 0),
    market_value REAL CHECK (market_value IS NULL OR market_value >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    valuation_as_of TEXT NOT NULL,
    valuation_method TEXT NOT NULL
        CHECK (valuation_method IN ('market_price', 'cost_basis', 'manual', 'unpriced')),
    coverage_status TEXT NOT NULL DEFAULT 'unpriced'
        CHECK (coverage_status IN ('covered', 'partial', 'unpriced', 'stale', 'invalid')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(currency)) BETWEEN 3 AND 12),
    CHECK ((valuation_method = 'unpriced' AND market_value IS NULL)
        OR (valuation_method <> 'unpriced' AND market_value IS NOT NULL)),
    CHECK ((valuation_method = 'market_price' AND market_price_snapshot_id IS NOT NULL)
        OR valuation_method <> 'market_price'),
    UNIQUE(investment_id, valuation_as_of)
);

CREATE INDEX IF NOT EXISTS idx_finance_market_price_instrument_as_of
    ON finance_market_price_snapshots(instrument_key, as_of DESC, quality);

CREATE INDEX IF NOT EXISTS idx_finance_valuation_investment_as_of
    ON finance_valuation_snapshots(investment_id, valuation_as_of DESC, coverage_status);
