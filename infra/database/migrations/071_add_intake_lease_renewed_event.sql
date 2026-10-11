-- Record lease heartbeats in the append-only intake audit trail.
-- SQLite cannot alter a CHECK constraint in place, so rebuild this small table.

DROP INDEX IF EXISTS idx_intake_events_intake;
ALTER TABLE intake_events RENAME TO intake_events_legacy;

CREATE TABLE intake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_id INTEGER NOT NULL REFERENCES intake_queue(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('queued', 'claimed', 'lease_renewed', 'landed', 'verified', 'rejected', 'failed', 'retried', 'cancelled')),
    actor TEXT NOT NULL DEFAULT 'system',
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(actor)) BETWEEN 1 AND 80),
    CHECK (length(trim(to_status)) BETWEEN 1 AND 32),
    CHECK (reason IS NULL OR length(reason) <= 500)
);

INSERT INTO intake_events
    (id, intake_id, event_type, actor, from_status, to_status, reason, created_at)
SELECT id, intake_id, event_type, actor, from_status, to_status, reason, created_at
FROM intake_events_legacy;

DROP TABLE intake_events_legacy;

CREATE INDEX idx_intake_events_intake
    ON intake_events(intake_id, created_at DESC);
