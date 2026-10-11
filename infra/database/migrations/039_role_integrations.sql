-- Migration 039: Atomic role integrations
-- Adds durable links between atomic roles, learning skills, and reviewable task routing.

CREATE TABLE IF NOT EXISTS role_skill_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id TEXT NOT NULL,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    learning_path TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'core' CHECK(link_type IN ('core', 'supporting')),
    source_registry TEXT NOT NULL DEFAULT 'docs/ROLE-LEARNING.yaml',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_role_skill_links_role ON role_skill_links(role_id);
CREATE INDEX IF NOT EXISTS idx_role_skill_links_skill ON role_skill_links(skill_id);

CREATE TABLE IF NOT EXISTS task_skill_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'suggested' CHECK(link_type IN ('suggested', 'accepted', 'dismissed')),
    match_reason TEXT NOT NULL,
    source_registry TEXT NOT NULL DEFAULT 'docs/ROLE-LEARNING.yaml',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, skill_id, source_registry)
);

CREATE INDEX IF NOT EXISTS idx_task_skill_links_task ON task_skill_links(task_id);
CREATE INDEX IF NOT EXISTS idx_task_skill_links_skill ON task_skill_links(skill_id);

CREATE TABLE IF NOT EXISTS task_role_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    role_id TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('high', 'medium', 'low')),
    match_reason TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'suggested' CHECK(review_status IN ('suggested', 'accepted', 'dismissed')),
    source_registry TEXT NOT NULL DEFAULT 'docs/ROLE-TASK-ROUTING.yaml',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, role_id, source_registry)
);

CREATE INDEX IF NOT EXISTS idx_task_role_suggestions_task ON task_role_suggestions(task_id);
CREATE INDEX IF NOT EXISTS idx_task_role_suggestions_role ON task_role_suggestions(role_id);
