-- Migration 020: ensure emails.category exists after partial 019 applies.
-- The migration runner skips ADD COLUMN when the column is already present.

ALTER TABLE emails ADD COLUMN category TEXT DEFAULT 'unclassified';
