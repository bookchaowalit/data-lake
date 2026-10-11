-- Additive, metadata-only CRM-to-finance evidence. No backfill or finance writes.
CREATE TABLE IF NOT EXISTS crm_workflow_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL REFERENCES crm_deals(id) ON DELETE RESTRICT,
    phase TEXT NOT NULL CHECK(phase IN ('lead','discovery','proposal','commitment','delivery','payment')),
    revision INTEGER NOT NULL CHECK(revision > 0),
    contract_version TEXT NOT NULL CHECK(contract_version='commercial-evidence.v1'),
    facts_json TEXT NOT NULL CHECK(json_valid(facts_json)),
    binding_hash TEXT NOT NULL CHECK(length(binding_hash)=64),
    upstream_id INTEGER REFERENCES crm_workflow_evidence(id) ON DELETE RESTRICT,
    supersedes_id INTEGER REFERENCES crm_workflow_evidence(id) ON DELETE RESTRICT,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE RESTRICT,
    transaction_id INTEGER REFERENCES financial_transactions(id) ON DELETE RESTRICT,
    reconciliation_id INTEGER REFERENCES finance_reconciliations(id) ON DELETE RESTRICT,
    intake_id INTEGER REFERENCES intake_queue(id) ON DELETE RESTRICT,
    actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 120),
    reason_code TEXT NOT NULL CHECK(length(reason_code) BETWEEN 1 AND 80),
    evidence_ref TEXT NOT NULL CHECK(length(evidence_ref) BETWEEN 1 AND 240),
    evidence_hash TEXT NOT NULL CHECK(length(evidence_hash)=64),
    verification_method TEXT NOT NULL DEFAULT 'owner-attested' CHECK(verification_method='owner-attested'),
    privacy_class TEXT NOT NULL DEFAULT 'restricted' CHECK(privacy_class='restricted'),
    retention_class TEXT NOT NULL DEFAULT 'financial-records' CHECK(retention_class='financial-records'),
    payload_hash TEXT NOT NULL UNIQUE CHECK(length(payload_hash)=64),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(deal_id,phase,revision)
);
CREATE INDEX IF NOT EXISTS idx_crm_workflow_evidence_latest ON crm_workflow_evidence(deal_id,phase,revision DESC);
CREATE TRIGGER IF NOT EXISTS crm_workflow_evidence_no_update
BEFORE UPDATE ON crm_workflow_evidence
BEGIN
    SELECT RAISE(ABORT,'commercial evidence is append-only; create a revision');
END;
CREATE TRIGGER IF NOT EXISTS crm_workflow_evidence_no_delete
BEFORE DELETE ON crm_workflow_evidence
BEGIN
    SELECT RAISE(ABORT,'commercial evidence retention requires an explicit reviewed procedure');
END;
