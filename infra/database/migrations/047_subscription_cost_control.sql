-- 047_subscription_cost_control.sql
-- Track recurring services separately from the transaction ledger so actual
-- payments, planned commitments, and value reviews remain auditable.

CREATE TABLE IF NOT EXISTS finance_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'software',
    owner_scope TEXT NOT NULL DEFAULT 'solo_empire'
        CHECK(owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('trial', 'active', 'paused', 'cancelled', 'expired')),
    billing_interval TEXT NOT NULL DEFAULT 'monthly'
        CHECK(billing_interval IN ('weekly', 'monthly', 'quarterly', 'yearly', 'one_time', 'usage')),
    amount REAL NOT NULL CHECK(amount >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    started_on DATE,
    next_billing_date DATE,
    cancelled_on DATE,
    auto_renew INTEGER NOT NULL DEFAULT 1 CHECK(auto_renew IN (0, 1)),
    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    source_ref TEXT,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, provider, owner_scope)
);

ALTER TABLE financial_transactions
    ADD COLUMN subscription_id INTEGER REFERENCES finance_subscriptions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS finance_subscription_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES finance_subscriptions(id) ON DELETE CASCADE,
    review_date DATE NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    usage_events INTEGER CHECK(usage_events IS NULL OR usage_events >= 0),
    usage_hours REAL CHECK(usage_hours IS NULL OR usage_hours >= 0),
    time_saved_hours REAL CHECK(time_saved_hours IS NULL OR time_saved_hours >= 0),
    revenue_attributed REAL CHECK(revenue_attributed IS NULL OR revenue_attributed >= 0),
    revenue_currency TEXT,
    value_score INTEGER CHECK(value_score IS NULL OR (value_score >= 0 AND value_score <= 100)),
    verdict TEXT NOT NULL DEFAULT 'insufficient_data'
        CHECK(verdict IN ('worth_it', 'conditional', 'not_worth_it', 'insufficient_data')),
    evidence TEXT,
    notes TEXT,
    next_review_date DATE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(subscription_id, review_date),
    CHECK(period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS finance_subscription_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL UNIQUE,
    subscription_id INTEGER REFERENCES finance_subscriptions(id) ON DELETE SET NULL,
    mapping_status TEXT NOT NULL DEFAULT 'unresolved'
        CHECK(mapping_status IN ('resolved', 'unresolved')),
    evidence TEXT,
    source TEXT NOT NULL DEFAULT 'subscription-review',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_finance_subscriptions_status
    ON finance_subscriptions(owner_scope, status, next_billing_date);
CREATE INDEX IF NOT EXISTS idx_finance_subscriptions_account
    ON finance_subscriptions(account_id);
CREATE INDEX IF NOT EXISTS idx_finance_subscriptions_project
    ON finance_subscriptions(project_id);
CREATE INDEX IF NOT EXISTS idx_finance_subscriptions_goal
    ON finance_subscriptions(goal_id);
CREATE INDEX IF NOT EXISTS idx_financial_transactions_subscription
    ON financial_transactions(subscription_id, transaction_type, transaction_date);
CREATE INDEX IF NOT EXISTS idx_finance_subscription_reviews_latest
    ON finance_subscription_reviews(subscription_id, review_date DESC);
CREATE INDEX IF NOT EXISTS idx_finance_subscription_aliases_subscription
    ON finance_subscription_aliases(subscription_id);
