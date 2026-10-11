-- Migration 001: Bootstrap schema_migrations table
-- This runs before any other migration to create the tracking table.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT DEFAULT (datetime('now')),
    description TEXT
);
