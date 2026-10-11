-- Migration 004: Fix financial_transactions primary key type
-- The old setup script created id as TEXT PRIMARY KEY, but schema.sql
-- specifies id INTEGER PRIMARY KEY AUTOINCREMENT.
-- SQLite cannot ALTER COLUMN types, so we rebuild the table.

-- Step 1: Create new table with correct schema
CREATE TABLE IF NOT EXISTS financial_transactions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    transaction_type TEXT,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'THB',
    description TEXT,
    category TEXT,
    merchant TEXT,
    transaction_date DATE NOT NULL,
    account TEXT,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Step 2: Copy data from old table, casting TEXT id to INTEGER
INSERT INTO financial_transactions_new (
    id, source, transaction_type, amount, currency, description,
    category, merchant, transaction_date, account, metadata, created_at
)
SELECT
    CASE
        WHEN typeof(id) = 'text' AND id GLOB '[0-9]*' THEN CAST(id AS INTEGER)
        ELSE NULL
    END,
    source, transaction_type, amount, currency, description,
    category, merchant, transaction_date, account, metadata, created_at
FROM financial_transactions;

-- Step 3: Drop old table
DROP TABLE financial_transactions;

-- Step 4: Rename new table
ALTER TABLE financial_transactions_new RENAME TO financial_transactions;

-- Step 5: Recreate indexes
CREATE INDEX IF NOT EXISTS idx_financial_transactions_date ON financial_transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_financial_transactions_category ON financial_transactions(category);
