-- 041_role_portfolio_links.sql
-- Make role execution a many-to-many portfolio: tasks can support goals and
-- roles can be allocated across projects without replacing existing links.

CREATE TABLE IF NOT EXISTS task_goal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'primary' CHECK(link_type IN ('primary', 'supporting')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, goal_id)
);

CREATE INDEX IF NOT EXISTS idx_task_goal_links_task ON task_goal_links(task_id);
CREATE INDEX IF NOT EXISTS idx_task_goal_links_goal ON task_goal_links(goal_id);

CREATE TABLE IF NOT EXISTS role_project_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id TEXT NOT NULL,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
    allocation_percent INTEGER NOT NULL DEFAULT 0 CHECK(allocation_percent >= 0 AND allocation_percent <= 100),
    priority INTEGER NOT NULL DEFAULT 3 CHECK(priority >= 1 AND priority <= 5),
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned', 'active', 'paused', 'completed')),
    source TEXT NOT NULL DEFAULT 'manual',
    start_date DATE,
    end_date DATE,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(role_id, project_id, goal_id)
);

CREATE INDEX IF NOT EXISTS idx_role_project_allocations_role ON role_project_allocations(role_id);
CREATE INDEX IF NOT EXISTS idx_role_project_allocations_project ON role_project_allocations(project_id);
CREATE INDEX IF NOT EXISTS idx_role_project_allocations_goal ON role_project_allocations(goal_id);

ALTER TABLE role_goal_links ADD COLUMN priority INTEGER NOT NULL DEFAULT 3;
ALTER TABLE role_goal_links ADD COLUMN allocation_percent INTEGER NOT NULL DEFAULT 0;
