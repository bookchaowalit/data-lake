-- Migration 002: Add columns that existed in the live DB but were missing from schema.sql
-- The migration runner catches "duplicate column" errors (idempotent).
-- If a column already exists, the ALTER TABLE is silently skipped.

-- skills: revenue relevance tracking
ALTER TABLE skills ADD COLUMN revenue_relevant BOOLEAN DEFAULT 0;
ALTER TABLE skills ADD COLUMN last_practiced DATE;

-- revenue: payment tracking
ALTER TABLE revenue ADD COLUMN received BOOLEAN DEFAULT 0;
