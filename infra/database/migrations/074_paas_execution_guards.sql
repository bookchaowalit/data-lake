-- Serialize provider mutations for one resource and retain an operator-visible
-- claim while a provider submission is pending or ambiguous.

ALTER TABLE decision_records ADD COLUMN execution_lock_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_records_execution_lock
    ON decision_records(execution_lock_key)
    WHERE execution_lock_key IS NOT NULL;
