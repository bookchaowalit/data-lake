ALTER TABLE revenue ADD COLUMN idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_revenue_idempotency
    ON revenue(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
