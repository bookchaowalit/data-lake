-- Migration 019: persist Gmail source records and audit their local routes.
ALTER TABLE emails ADD COLUMN category TEXT DEFAULT 'unclassified';
ALTER TABLE emails ADD COLUMN pipeline_status TEXT DEFAULT 'pending';
ALTER TABLE emails ADD COLUMN pipeline_processed_at DATETIME;
ALTER TABLE emails ADD COLUMN pipeline_error TEXT;

CREATE TABLE IF NOT EXISTS data_pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_name TEXT NOT NULL,
    source TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'partial', 'error')),
    records_read INTEGER DEFAULT 0,
    records_persisted INTEGER DEFAULT 0,
    records_routed INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    error_message TEXT,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('success', 'skipped', 'error')),
    target_type TEXT,
    target_id TEXT,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email_id, action_type)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source ON data_pipeline_runs(source, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_email ON email_pipeline_events(email_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_action ON email_pipeline_events(action_type, status);
CREATE INDEX IF NOT EXISTS idx_emails_pipeline_status ON emails(pipeline_status, received_at DESC);
