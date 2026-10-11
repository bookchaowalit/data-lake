-- 046_cross_domain_gap_registry.sql
-- Keep unresolved cross-domain references reviewable without guessing links.

CREATE TABLE IF NOT EXISTS finance_account_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL UNIQUE,
    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
    mapping_status TEXT NOT NULL DEFAULT 'unresolved' CHECK(mapping_status IN ('resolved', 'unresolved')),
    evidence TEXT,
    source TEXT NOT NULL DEFAULT 'entity-graph',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_finance_account_aliases_account ON finance_account_aliases(account_id);
CREATE INDEX IF NOT EXISTS idx_finance_account_aliases_status ON finance_account_aliases(mapping_status);

ALTER TABLE financial_transactions ADD COLUMN account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS entity_gap_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_type TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'accepted', 'dismissed', 'resolved')),
    recommended_action TEXT NOT NULL,
    candidate_target TEXT,
    evidence TEXT,
    source TEXT NOT NULL DEFAULT 'entity-graph',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gap_type, source_table, source_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_gap_reviews_status ON entity_gap_reviews(status);
CREATE INDEX IF NOT EXISTS idx_entity_gap_reviews_source ON entity_gap_reviews(source_table, source_id);
