-- Migration 077: Add agency pipeline stage and vertical metadata.
-- Keep the crm_deals table name stable so existing foreign-key references remain valid.
PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

CREATE TABLE crm_deals_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    project_id INTEGER REFERENCES projects(id),
    stage TEXT CHECK(stage IN ('lead', 'contacted', 'discovery', 'proposal', 'negotiation', 'closed_won', 'closed_lost', 'churned')) DEFAULT 'lead',
    probability INTEGER DEFAULT 0 CHECK(probability >= 0 AND probability <= 100),
    deal_value REAL,
    currency TEXT DEFAULT 'THB',
    expected_close_date DATE,
    actual_close_date DATE,
    service_type TEXT,
    vertical TEXT,
    source TEXT,
    priority INTEGER DEFAULT 3,
    last_contact_date DATE,
    next_action TEXT,
    next_action_date DATE,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO crm_deals_new (
    id, title, client_id, project_id, stage, probability, deal_value, currency,
    expected_close_date, actual_close_date, service_type, source, priority,
    last_contact_date, next_action, next_action_date, notes, created_at, updated_at
)
SELECT
    id, title, client_id, project_id, stage, probability, deal_value, currency,
    expected_close_date, actual_close_date, service_type, source, priority,
    last_contact_date, next_action, next_action_date, notes, created_at, updated_at
FROM crm_deals;

DROP TABLE crm_deals;
ALTER TABLE crm_deals_new RENAME TO crm_deals;

CREATE INDEX idx_crm_deals_stage ON crm_deals(stage);
CREATE INDEX idx_crm_deals_client ON crm_deals(client_id);
CREATE INDEX idx_crm_deals_project ON crm_deals(project_id);
CREATE INDEX idx_crm_deals_vertical ON crm_deals(vertical);

COMMIT;
PRAGMA foreign_keys = ON;
