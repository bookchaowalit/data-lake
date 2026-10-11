-- Agency workflow state extends the existing CRM and finance projections.
CREATE TABLE IF NOT EXISTS crm_agency_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL UNIQUE REFERENCES crm_deals(id) ON DELETE CASCADE,
    notice_version TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'inquiry',
    status TEXT NOT NULL CHECK(status IN ('active', 'withdrawn')),
    retention_until DATE NOT NULL,
    receipt_hash TEXT NOT NULL UNIQUE,
    request_key_hash TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    contact_hash TEXT NOT NULL,
    evidence_ref TEXT,
    recorded_at TEXT NOT NULL,
    withdrawn_at TEXT
);

CREATE TABLE IF NOT EXISTS crm_agency_deal_state (
    deal_id INTEGER PRIMARY KEY REFERENCES crm_deals(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO crm_agency_deal_state (deal_id)
SELECT id FROM crm_deals WHERE vertical IN ('talent', 'real-estate');

CREATE TRIGGER IF NOT EXISTS crm_agency_deal_revision
AFTER UPDATE ON crm_deals
WHEN NEW.vertical IN ('talent', 'real-estate')
BEGIN
    INSERT INTO crm_agency_deal_state (deal_id, revision) VALUES (NEW.id, 1)
    ON CONFLICT(deal_id) DO UPDATE SET revision = revision + 1;
END;

CREATE TABLE IF NOT EXISTS crm_agency_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_at TEXT NOT NULL UNIQUE,
    end_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(end_at > start_at)
);

CREATE TABLE IF NOT EXISTS crm_agency_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL REFERENCES crm_deals(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    slot_id INTEGER UNIQUE REFERENCES crm_agency_slots(id),
    calendar_event_id TEXT UNIQUE REFERENCES calendar_events(id),
    status TEXT NOT NULL DEFAULT 'invited' CHECK(status IN ('invited', 'booked', 'cancelled')),
    created_at TEXT NOT NULL,
    booked_at TEXT
);

CREATE TABLE IF NOT EXISTS crm_agency_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL REFERENCES crm_deals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('new_lead', 'follow_up', 'booking')),
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued', 'delivering', 'delivered', 'failed', 'unknown', 'dismissed')),
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    error_code TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crm_agency_offers (
    vertical TEXT PRIMARY KEY CHECK(vertical IN ('talent', 'real-estate')),
    title TEXT NOT NULL,
    price REAL CHECK(price IS NULL OR price > 0),
    currency TEXT NOT NULL DEFAULT 'THB' CHECK(currency IN ('THB', 'USD')),
    delivery_days INTEGER NOT NULL DEFAULT 14 CHECK(delivery_days BETWEEN 1 AND 365),
    commercial_review_ref TEXT,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO crm_agency_offers (vertical, title, updated_at) VALUES
    ('talent', 'Specialist Technical Search Pilot', CURRENT_TIMESTAMP),
    ('real-estate', 'Condo Rental Validation Pilot', CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS crm_agency_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL REFERENCES crm_deals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('proposal', 'contract')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'approved', 'sent', 'accepted')),
    parent_id INTEGER REFERENCES crm_agency_documents(id),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 16000),
    content_hash TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    currency TEXT NOT NULL CHECK(currency IN ('THB', 'USD')),
    request_key_hash TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    legal_review_ref TEXT,
    approved_by TEXT,
    approved_at TEXT,
    signing_url TEXT,
    signature_evidence_ref TEXT,
    signer_name TEXT,
    accepted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_agency_invoice_links (
    deal_id INTEGER PRIMARY KEY REFERENCES crm_deals(id),
    contract_id INTEGER NOT NULL UNIQUE REFERENCES crm_agency_documents(id),
    invoice_id INTEGER NOT NULL UNIQUE REFERENCES invoices(id),
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS crm_agency_document_immutable
BEFORE UPDATE OF deal_id, kind, parent_id, content, content_hash, amount, currency, request_key_hash, payload_hash
ON crm_agency_documents
BEGIN
    SELECT RAISE(ABORT, 'agency document content is immutable; create a new revision');
END;

CREATE INDEX IF NOT EXISTS idx_crm_agency_retention ON crm_agency_consents(status, retention_until);
CREATE INDEX IF NOT EXISTS idx_crm_agency_contact_consent ON crm_agency_consents(contact_hash, status);
CREATE INDEX IF NOT EXISTS idx_crm_agency_notification_queue ON crm_agency_notifications(status, created_at);
CREATE INDEX IF NOT EXISTS idx_crm_agency_documents_deal ON crm_agency_documents(deal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_crm_agency_booking_deal ON crm_agency_bookings(deal_id, status);
