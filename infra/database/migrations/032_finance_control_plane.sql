-- Finance Control Plane v1.
-- These tables hold scoped metadata and planning/control records only. They do
-- not store credentials, tax IDs, or raw bank statements.

CREATE TABLE IF NOT EXISTS finance_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL
        CHECK (account_type IN ('bank', 'cash', 'wallet', 'payment', 'credit', 'investment', 'receivable', 'other')),
    owner_scope TEXT NOT NULL DEFAULT 'personal'
        CHECK (owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    institution TEXT,
    currency TEXT NOT NULL DEFAULT 'THB',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('planned', 'active', 'paused', 'closed')),
    opening_balance REAL,
    opened_on DATE,
    closed_on DATE,
    metadata TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, owner_scope)
);

CREATE TABLE IF NOT EXISTS finance_budget_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_scope TEXT NOT NULL DEFAULT 'solo_empire'
        CHECK (owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    category TEXT,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    planned_amount REAL NOT NULL CHECK (planned_amount >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'closed', 'cancelled')),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS finance_cashflow_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_scope TEXT NOT NULL DEFAULT 'solo_empire'
        CHECK (owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    expected_inflow REAL NOT NULL DEFAULT 0 CHECK (expected_inflow >= 0),
    expected_outflow REAL NOT NULL DEFAULT 0 CHECK (expected_outflow >= 0),
    reserve_target REAL CHECK (reserve_target IS NULL OR reserve_target >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'closed', 'cancelled')),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS finance_liabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    liability_type TEXT NOT NULL
        CHECK (liability_type IN ('loan', 'credit', 'tax', 'payable', 'subscription', 'other')),
    owner_scope TEXT NOT NULL DEFAULT 'personal'
        CHECK (owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
    principal_amount REAL CHECK (principal_amount IS NULL OR principal_amount >= 0),
    outstanding_amount REAL CHECK (outstanding_amount IS NULL OR outstanding_amount >= 0),
    minimum_payment REAL CHECK (minimum_payment IS NULL OR minimum_payment >= 0),
    interest_rate_percent REAL CHECK (interest_rate_percent IS NULL OR interest_rate_percent >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('planned', 'active', 'overdue', 'settled', 'cancelled')),
    metadata TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    investment_type TEXT NOT NULL
        CHECK (investment_type IN ('stock', 'etf', 'fund', 'bond', 'crypto', 'real_estate', 'business', 'other')),
    owner_scope TEXT NOT NULL DEFAULT 'personal'
        CHECK (owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
    quantity REAL CHECK (quantity IS NULL OR quantity >= 0),
    cost_basis REAL CHECK (cost_basis IS NULL OR cost_basis >= 0),
    current_value REAL CHECK (current_value IS NULL OR current_value >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    acquired_on DATE,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('planned', 'active', 'sold', 'closed')),
    metadata TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_tax_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_year INTEGER NOT NULL CHECK (tax_year >= 2000),
    jurisdiction TEXT NOT NULL DEFAULT 'TH',
    tax_type TEXT NOT NULL
        CHECK (tax_type IN ('income', 'vat', 'withholding', 'property', 'social_security', 'other')),
    period_start DATE,
    period_end DATE,
    amount_due REAL CHECK (amount_due IS NULL OR amount_due >= 0),
    amount_paid REAL NOT NULL DEFAULT 0 CHECK (amount_paid >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'estimated'
        CHECK (status IN ('estimated', 'open', 'filed', 'paid', 'waived', 'overdue')),
    evidence_ref TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS finance_reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('bank_statement', 'wallet_export', 'invoice_register', 'manual', 'other')),
    source_ref TEXT,
    expected_amount REAL,
    reconciled_amount REAL,
    difference_amount REAL,
    currency TEXT NOT NULL DEFAULT 'THB',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'matched', 'exception', 'closed')),
    reconciled_at DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (period_end >= period_start)
);

CREATE INDEX IF NOT EXISTS idx_finance_accounts_scope
    ON finance_accounts(owner_scope, status);
CREATE INDEX IF NOT EXISTS idx_finance_budget_period
    ON finance_budget_plans(period_start, period_end, status);
CREATE INDEX IF NOT EXISTS idx_finance_cashflow_period
    ON finance_cashflow_plans(period_start, period_end, status);
CREATE INDEX IF NOT EXISTS idx_finance_liabilities_status
    ON finance_liabilities(owner_scope, status, due_date);
CREATE INDEX IF NOT EXISTS idx_finance_investments_status
    ON finance_investments(owner_scope, status);
CREATE INDEX IF NOT EXISTS idx_finance_tax_due
    ON finance_tax_items(tax_year, status, due_date);
CREATE INDEX IF NOT EXISTS idx_finance_reconciliations_period
    ON finance_reconciliations(period_start, period_end, status);
