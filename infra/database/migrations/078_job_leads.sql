-- Migration 078: Freelance Lead Radar job lead projection (task L1.2 #217).
-- Rows come from the owner's own Upwork/Fastwork notification email; the
-- radar never scrapes platforms or sends messages. Buyer names are not stored.
-- infra/scripts/sync/job_lead_radar.py applies the same idempotent DDL.

CREATE TABLE IF NOT EXISTS job_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK(source IN ('upwork', 'fastwork')),
    kind TEXT NOT NULL CHECK(kind IN ('job_post', 'invitation', 'inbound_order')),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    description TEXT,
    budget_type TEXT CHECK(budget_type IN ('fixed', 'hourly') OR budget_type IS NULL),
    budget_amount REAL,
    currency TEXT,
    duration TEXT,
    gmail_message_id TEXT NOT NULL,
    received_at DATETIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
        CHECK(status IN ('new', 'filtered_out', 'scored', 'drafted', 'sent', 'skipped', 'snoozed')),
    filter_reason TEXT,
    matched_service TEXT,
    score INTEGER CHECK(score IS NULL OR (score >= 0 AND score <= 100)),
    score_reasons TEXT,
    scored_at DATETIME,
    notified_at DATETIME,
    crm_deal_id INTEGER REFERENCES crm_deals(id) ON DELETE SET NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_job_leads_status_received ON job_leads(status, received_at);
