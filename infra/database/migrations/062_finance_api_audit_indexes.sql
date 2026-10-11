-- Migration 062: Finance API audit query indexes
-- Keep the existing generic audit_log table usable for the read-only API
-- without adding a second audit store.

CREATE INDEX IF NOT EXISTS idx_audit_log_target_action_created
  ON audit_log(target_type, action, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_created
  ON audit_log(created_at DESC);
