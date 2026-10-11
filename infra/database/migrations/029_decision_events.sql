CREATE TABLE IF NOT EXISTS decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decision_records(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('created', 'refreshed', 'approved', 'rejected', 'deferred', 'completed', 'signal_cleared')),
    actor TEXT NOT NULL DEFAULT 'system',
    from_status TEXT,
    to_status TEXT,
    from_approval_status TEXT,
    to_approval_status TEXT,
    from_action_status TEXT,
    to_action_status TEXT,
    reason TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decision_events_decision
    ON decision_events(decision_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_events_type
    ON decision_events(event_type, created_at DESC);
