-- Migration 064: Finance allocation control
-- Extend the existing budget-plan control plane with explicit allocation
-- waterfall metadata. This stores planning rules only and never moves money.

ALTER TABLE finance_budget_plans
    ADD COLUMN allocation_bucket TEXT;

ALTER TABLE finance_budget_plans
    ADD COLUMN allocation_method TEXT NOT NULL DEFAULT 'budget'
        CHECK (allocation_method IN (
            'budget', 'fixed_commitment', 'target', 'hold', 'remainder', 'blocked'
        ));

ALTER TABLE finance_budget_plans
    ADD COLUMN allocation_priority INTEGER NOT NULL DEFAULT 0
        CHECK (allocation_priority >= 0);

ALTER TABLE finance_budget_plans
    ADD COLUMN allocation_percent REAL
        CHECK (allocation_percent IS NULL OR (allocation_percent >= 0 AND allocation_percent <= 100));

ALTER TABLE finance_budget_plans
    ADD COLUMN source_ref TEXT;

CREATE INDEX IF NOT EXISTS idx_finance_budget_allocation
    ON finance_budget_plans(allocation_bucket, allocation_method, period_start, status);
