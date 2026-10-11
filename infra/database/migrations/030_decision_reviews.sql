DROP INDEX IF EXISTS idx_decision_events_decision;
DROP INDEX IF EXISTS idx_decision_events_type;
ALTER TABLE decision_events RENAME TO decision_events_legacy;

CREATE TABLE decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decision_records(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('created', 'refreshed', 'approved', 'rejected', 'deferred', 'completed', 'signal_cleared', 'review_task_created', 'reviewed')),
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

INSERT INTO decision_events (
    id, decision_id, event_type, actor,
    from_status, to_status,
    from_approval_status, to_approval_status,
    from_action_status, to_action_status,
    reason, metadata, created_at
)
SELECT id, decision_id, event_type, actor,
       from_status, to_status,
       from_approval_status, to_approval_status,
       from_action_status, to_action_status,
       reason, metadata, created_at
FROM decision_events_legacy;

DROP TABLE decision_events_legacy;

CREATE INDEX idx_decision_events_decision
    ON decision_events(decision_id, created_at DESC);
CREATE INDEX idx_decision_events_type
    ON decision_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decision_records(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    due_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'skipped')),
    reviewer TEXT,
    outcome TEXT,
    notes TEXT,
    reviewed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(decision_id, due_date)
);

CREATE INDEX IF NOT EXISTS idx_decision_reviews_decision
    ON decision_reviews(decision_id, due_date DESC);
CREATE INDEX IF NOT EXISTS idx_decision_reviews_due
    ON decision_reviews(status, due_date);
