CREATE TABLE IF NOT EXISTS decision_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'general',
    decision TEXT NOT NULL,
    rationale TEXT,
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    expected_outcome TEXT,
    actual_outcome TEXT,
    next_action TEXT,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('draft', 'proposed', 'approved', 'in_progress', 'completed', 'deferred', 'rejected', 'superseded')),
    approval_required INTEGER NOT NULL DEFAULT 1 CHECK (approval_required IN (0, 1)),
    approval_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (approval_status IN ('pending', 'approved', 'rejected', 'not_required')),
    action_type TEXT NOT NULL DEFAULT 'none'
        CHECK (action_type IN ('none', 'task', 'calendar', 'notification', 'message', 'financial', 'external_change')),
    action_status TEXT NOT NULL DEFAULT 'none'
        CHECK (action_status IN ('none', 'pending_approval', 'queued', 'executed', 'blocked', 'failed')),
    privacy_class TEXT NOT NULL DEFAULT 'private'
        CHECK (privacy_class IN ('private', 'sensitive', 'internal')),
    source_type TEXT,
    source_ref TEXT,
    review_date DATE,
    decided_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decision_records_status
    ON decision_records(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_records_approval
    ON decision_records(approval_status, approval_required);
CREATE INDEX IF NOT EXISTS idx_decision_records_review
    ON decision_records(review_date);
CREATE INDEX IF NOT EXISTS idx_decision_records_domain
    ON decision_records(domain, created_at DESC);
