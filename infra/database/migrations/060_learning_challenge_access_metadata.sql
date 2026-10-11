-- Migration 060: learning challenge provider and access metadata

ALTER TABLE learning_challenges
    ADD COLUMN category TEXT NOT NULL DEFAULT 'coding';

ALTER TABLE learning_challenges
    ADD COLUMN is_external INTEGER NOT NULL DEFAULT 0 CHECK(is_external IN (0, 1));

ALTER TABLE learning_challenges
    ADD COLUMN free_access INTEGER NOT NULL DEFAULT 0 CHECK(free_access IN (0, 1));

ALTER TABLE learning_challenges
    ADD COLUMN account_required INTEGER NOT NULL DEFAULT 0 CHECK(account_required IN (0, 1));

ALTER TABLE learning_challenges
    ADD COLUMN access_model TEXT NOT NULL DEFAULT 'local';

ALTER TABLE learning_challenges
    ADD COLUMN access_notes TEXT;

ALTER TABLE learning_challenges
    ADD COLUMN access_source_url TEXT;

CREATE INDEX IF NOT EXISTS idx_learning_challenges_access
    ON learning_challenges(is_external, free_access, category, provider);
