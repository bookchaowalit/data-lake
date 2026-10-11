-- Source Registry + lake-first Intake Queue.
--
-- These tables are control-plane metadata only. They intentionally do not
-- store source payloads, credentials, absolute file paths, or raw private
-- content. Payloads belong in the data lake landing/Bronze layers first.

CREATE TABLE IF NOT EXISTS source_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source_kind TEXT NOT NULL
        CHECK (source_kind IN ('manual', 'file', 'api', 'webhook', 'email', 'calendar', 'database', 'application', 'other')),
    provider TEXT,
    domain TEXT NOT NULL,
    dataset TEXT NOT NULL,
    owner_scope TEXT NOT NULL DEFAULT 'solo_empire'
        CHECK (owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    privacy_class TEXT NOT NULL DEFAULT 'private'
        CHECK (privacy_class IN ('public', 'internal', 'private', 'restricted')),
    retention_class TEXT NOT NULL DEFAULT 'operational'
        CHECK (length(trim(retention_class)) BETWEEN 1 AND 64),
    ingest_mode TEXT NOT NULL DEFAULT 'manual'
        CHECK (ingest_mode IN ('manual', 'batch', 'stream', 'webhook')),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'active', 'paused', 'retired')),
    description TEXT,
    last_ingested_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(source_key)) BETWEEN 1 AND 64),
    CHECK (length(trim(display_name)) BETWEEN 1 AND 160),
    CHECK (length(trim(domain)) BETWEEN 1 AND 80),
    CHECK (length(trim(dataset)) BETWEEN 1 AND 120)
);

CREATE TABLE IF NOT EXISTS intake_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_key TEXT NOT NULL UNIQUE,
    source_id INTEGER NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
    domain TEXT NOT NULL,
    dataset TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1',
    payload_kind TEXT NOT NULL
        CHECK (payload_kind IN ('json', 'jsonl', 'csv', 'binary', 'markdown', 'parquet', 'other')),
    input_ref TEXT NOT NULL,
    source_batch_ref TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    privacy_class TEXT NOT NULL DEFAULT 'private'
        CHECK (privacy_class IN ('public', 'internal', 'private', 'restricted')),
    retention_class TEXT NOT NULL DEFAULT 'operational'
        CHECK (length(trim(retention_class)) BETWEEN 1 AND 64),
    requested_by TEXT NOT NULL DEFAULT 'human'
        CHECK (requested_by IN ('human', 'agent', 'automation')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'landed', 'verified', 'rejected', 'failed', 'cancelled')),
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    claimed_at DATETIME,
    lease_owner TEXT,
    lease_expires_at DATETIME,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    record_count INTEGER CHECK (record_count IS NULL OR record_count >= 0),
    raw_sha256 TEXT
        CHECK (raw_sha256 IS NULL OR (length(raw_sha256) = 64 AND raw_sha256 NOT GLOB '*[^0-9a-fA-F]*')),
    lake_run_id TEXT,
    lake_manifest_key TEXT,
    lake_raw_object_key TEXT,
    lake_bronze_object_key TEXT,
    error_code TEXT,
    error_message TEXT,
    verified_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(intake_key)) BETWEEN 1 AND 96),
    CHECK (length(trim(domain)) BETWEEN 1 AND 80),
    CHECK (length(trim(dataset)) BETWEEN 1 AND 120),
    CHECK (length(trim(schema_version)) BETWEEN 1 AND 32),
    CHECK (length(trim(input_ref)) BETWEEN 1 AND 240),
    CHECK (source_batch_ref IS NULL OR length(trim(source_batch_ref)) BETWEEN 1 AND 160),
    CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 160),
    CHECK (lake_manifest_key IS NULL OR length(trim(lake_manifest_key)) BETWEEN 1 AND 512),
    CHECK (lake_raw_object_key IS NULL OR length(trim(lake_raw_object_key)) BETWEEN 1 AND 512),
    CHECK (lake_bronze_object_key IS NULL OR length(trim(lake_bronze_object_key)) BETWEEN 1 AND 512),
    CHECK (error_code IS NULL OR length(trim(error_code)) BETWEEN 1 AND 80),
    CHECK (error_message IS NULL OR length(error_message) <= 500)
);

CREATE TABLE IF NOT EXISTS intake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_id INTEGER NOT NULL REFERENCES intake_queue(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('queued', 'claimed', 'landed', 'verified', 'rejected', 'failed', 'retried', 'cancelled')),
    actor TEXT NOT NULL DEFAULT 'system',
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(actor)) BETWEEN 1 AND 80),
    CHECK (length(trim(to_status)) BETWEEN 1 AND 32),
    CHECK (reason IS NULL OR length(reason) <= 500)
);

CREATE INDEX IF NOT EXISTS idx_source_registry_status
    ON source_registry(status, domain, dataset);

CREATE INDEX IF NOT EXISTS idx_source_registry_privacy
    ON source_registry(privacy_class, owner_scope);

CREATE INDEX IF NOT EXISTS idx_intake_queue_status
    ON intake_queue(status, requested_at);

CREATE INDEX IF NOT EXISTS idx_intake_queue_source
    ON intake_queue(source_id, status, requested_at);

CREATE INDEX IF NOT EXISTS idx_intake_queue_lease
    ON intake_queue(status, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_intake_events_intake
    ON intake_events(intake_id, created_at DESC);

