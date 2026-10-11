-- Migration 040: Atomic role capability paths
-- Projects each role through goal selection, learning, practice, evidence, and operation.

CREATE TABLE IF NOT EXISTS role_path_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id TEXT NOT NULL,
    step_key TEXT NOT NULL,
    phase_id TEXT NOT NULL CHECK(phase_id IN ('orient', 'learn', 'practice', 'evidence', 'operate')),
    title TEXT NOT NULL,
    action TEXT NOT NULL,
    completion_rule TEXT NOT NULL,
    skill_id INTEGER REFERENCES skills(id) ON DELETE SET NULL,
    target_progress INTEGER CHECK(target_progress >= 0 AND target_progress <= 100),
    evidence_path TEXT,
    source_registry TEXT NOT NULL DEFAULT 'docs/ROLE-PATHS.yaml',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, step_key, source_registry)
);

CREATE INDEX IF NOT EXISTS idx_role_path_steps_role ON role_path_steps(role_id);
CREATE INDEX IF NOT EXISTS idx_role_path_steps_phase ON role_path_steps(phase_id);
CREATE INDEX IF NOT EXISTS idx_role_path_steps_skill ON role_path_steps(skill_id);

CREATE TABLE IF NOT EXISTS role_goal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id TEXT NOT NULL,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'primary' CHECK(link_type IN ('primary', 'supporting')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, goal_id)
);

CREATE INDEX IF NOT EXISTS idx_role_goal_links_role ON role_goal_links(role_id);
CREATE INDEX IF NOT EXISTS idx_role_goal_links_goal ON role_goal_links(goal_id);
