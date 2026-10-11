ALTER TABLE emails ADD COLUMN lake_event_id TEXT;
ALTER TABLE emails ADD COLUMN lake_run_id TEXT;
ALTER TABLE emails ADD COLUMN lake_snapshot_id TEXT;
ALTER TABLE emails ADD COLUMN lake_table TEXT;
ALTER TABLE emails ADD COLUMN lake_raw_object_key TEXT;

CREATE INDEX IF NOT EXISTS idx_emails_lake_event ON emails(lake_event_id);
CREATE INDEX IF NOT EXISTS idx_emails_lake_run ON emails(lake_run_id);
