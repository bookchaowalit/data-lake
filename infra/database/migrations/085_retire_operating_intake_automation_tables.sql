-- Retire the operating, intake and automation tables from the control plane (owner direction
-- 2026-10-10, one cell = one repo, backend and database). The rows live in three cells made with
-- solo-cell-kit: solo-operating, solo-intake and solo-automation (each with its own Neon database).
-- Imported rows keep their old ids. Every reader and writer goes through
-- infra/scripts/utils/cell_store.py or infra/mcp-server/src/cell-store.ts. The old DDL lives on for
-- tests in infra/tests/support/legacy_operating_intake_automation_tables.sql.
--
-- Guard: nothing is dropped until the cutover recorded a verified import of every cell in
-- cell_cutovers (cellkit-import --verify: every old row is in the cell).
-- Foreign keys are off and everything runs in one transaction (see 084).
PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TEMP TABLE retire_operating_guard (verified INTEGER NOT NULL CHECK (verified = 3));
INSERT INTO retire_operating_guard
    SELECT count(*) FROM cell_cutovers WHERE cell IN ('operating', 'intake', 'automation');
DROP TABLE retire_operating_guard;

-- crm_workflow_evidence keeps its rows but loses the foreign key into intake_queue (a plain id now).
CREATE TEMP TABLE retire_operating_sequences AS SELECT name, seq FROM sqlite_sequence WHERE name = 'crm_workflow_evidence';
CREATE TABLE "crm_workflow_evidence__new" (
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
    intake_id INTEGER,
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
INSERT INTO "crm_workflow_evidence__new" ("id", "deal_id", "phase", "revision", "contract_version", "facts_json", "binding_hash", "upstream_id", "supersedes_id", "invoice_id", "transaction_id", "reconciliation_id", "intake_id", "actor_ref", "reason_code", "evidence_ref", "evidence_hash", "verification_method", "privacy_class", "retention_class", "payload_hash", "recorded_at") SELECT "id", "deal_id", "phase", "revision", "contract_version", "facts_json", "binding_hash", "upstream_id", "supersedes_id", "invoice_id", "transaction_id", "reconciliation_id", "intake_id", "actor_ref", "reason_code", "evidence_ref", "evidence_hash", "verification_method", "privacy_class", "retention_class", "payload_hash", "recorded_at" FROM "crm_workflow_evidence";
DROP TABLE "crm_workflow_evidence";
ALTER TABLE "crm_workflow_evidence__new" RENAME TO "crm_workflow_evidence";
CREATE INDEX idx_crm_workflow_evidence_latest ON crm_workflow_evidence(deal_id,phase,revision DESC);
CREATE TRIGGER crm_workflow_evidence_no_update
BEFORE UPDATE ON crm_workflow_evidence
BEGIN
    SELECT RAISE(ABORT,'commercial evidence is append-only; create a revision');
END;
CREATE TRIGGER crm_workflow_evidence_no_delete
BEFORE DELETE ON crm_workflow_evidence
BEGIN
    SELECT RAISE(ABORT,'commercial evidence retention requires an explicit reviewed procedure');
END;
UPDATE sqlite_sequence SET seq = (SELECT k.seq FROM retire_operating_sequences k WHERE k.name = sqlite_sequence.name)
    WHERE name IN (SELECT name FROM retire_operating_sequences)
      AND seq < (SELECT k.seq FROM retire_operating_sequences k WHERE k.name = sqlite_sequence.name);
INSERT INTO sqlite_sequence (name, seq)
    SELECT name, seq FROM retire_operating_sequences WHERE name NOT IN (SELECT name FROM sqlite_sequence);
DROP TABLE retire_operating_sequences;

DROP TABLE IF EXISTS operating_kpi_measurements;
DROP TABLE IF EXISTS operating_cycle_reviews;
DROP TABLE IF EXISTS operating_cycle_goal_links;
DROP TABLE IF EXISTS operating_cycle_tasks;
DROP TABLE IF EXISTS operating_kpi_definitions;
DROP TABLE IF EXISTS operating_cycles;
DROP TABLE IF EXISTS intake_events;
DROP TABLE IF EXISTS intake_queue;
DROP TABLE IF EXISTS source_registry;
DROP TABLE IF EXISTS automation_log;
DROP TABLE IF EXISTS automation_rules;
DROP TABLE IF EXISTS workflow_pipelines;
DROP TABLE IF EXISTS cron_jobs;

COMMIT;
PRAGMA foreign_keys = ON;
