ALTER TABLE decision_records ADD COLUMN dedupe_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_records_dedupe
    ON decision_records(dedupe_key)
    WHERE dedupe_key IS NOT NULL;
