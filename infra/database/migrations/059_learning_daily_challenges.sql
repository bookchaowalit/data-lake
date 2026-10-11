-- Migration 059: learning daily challenges

CREATE TABLE IF NOT EXISTS learning_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_key TEXT NOT NULL UNIQUE,
    track TEXT NOT NULL,
    challenge_type TEXT NOT NULL CHECK(challenge_type IN ('coding', 'quiz', 'study', 'project', 'competition')),
    provider TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    instructions TEXT,
    url TEXT,
    difficulty TEXT,
    estimated_minutes INTEGER CHECK(estimated_minutes IS NULL OR estimated_minutes > 0),
    rotation_order INTEGER NOT NULL DEFAULT 0 CHECK(rotation_order >= 0),
    tags_json TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learning_challenge_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER NOT NULL REFERENCES learning_challenges(id) ON DELETE CASCADE,
    assignment_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'assigned'
        CHECK(status IN ('assigned', 'in_progress', 'completed', 'skipped')),
    score_percent INTEGER CHECK(score_percent IS NULL OR score_percent BETWEEN 0 AND 100),
    time_spent_minutes REAL CHECK(time_spent_minutes IS NULL OR time_spent_minutes >= 0),
    solution_url TEXT,
    notes TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(challenge_id, assignment_date)
);

CREATE INDEX IF NOT EXISTS idx_learning_challenges_track
    ON learning_challenges(track, is_active, rotation_order);

CREATE INDEX IF NOT EXISTS idx_learning_challenge_assignments_date
    ON learning_challenge_assignments(assignment_date, status);

CREATE INDEX IF NOT EXISTS idx_learning_challenge_assignments_challenge
    ON learning_challenge_assignments(challenge_id, assignment_date);
