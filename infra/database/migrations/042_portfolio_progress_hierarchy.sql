-- 042_portfolio_progress_hierarchy.sql
-- Add an always-on Goal → Epic/Story → Project → Task → Subtask hierarchy.

CREATE TABLE IF NOT EXISTS goal_project_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'delivery' CHECK(relation_type IN ('delivery', 'supporting')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(goal_id, project_id)
);

CREATE TABLE IF NOT EXISTS portfolio_work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL CHECK(item_type IN ('epic', 'story')),
    title TEXT NOT NULL,
    description TEXT,
    goal_id INTEGER REFERENCES goals(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_item_id INTEGER REFERENCES portfolio_work_items(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo', 'in_progress', 'done', 'blocked', 'cancelled')),
    progress_percent INTEGER NOT NULL DEFAULT 0 CHECK(progress_percent >= 0 AND progress_percent <= 100),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS work_item_task_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER NOT NULL REFERENCES portfolio_work_items(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'implements' CHECK(relation_type IN ('implements', 'supports')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(work_item_id, task_id)
);

CREATE TABLE IF NOT EXISTS task_project_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'delivery' CHECK(relation_type IN ('delivery', 'supporting')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, project_id)
);

ALTER TABLE tasks ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0 CHECK(progress_percent >= 0 AND progress_percent <= 100);
ALTER TABLE goal_tasks ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0 CHECK(progress_percent >= 0 AND progress_percent <= 100);

CREATE INDEX IF NOT EXISTS idx_goal_project_links_goal ON goal_project_links(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_project_links_project ON goal_project_links(project_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_work_items_goal ON portfolio_work_items(goal_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_work_items_project ON portfolio_work_items(project_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_work_items_parent ON portfolio_work_items(parent_item_id);
CREATE INDEX IF NOT EXISTS idx_work_item_task_links_item ON work_item_task_links(work_item_id);
CREATE INDEX IF NOT EXISTS idx_work_item_task_links_task ON work_item_task_links(task_id);
CREATE INDEX IF NOT EXISTS idx_task_project_links_task ON task_project_links(task_id);
CREATE INDEX IF NOT EXISTS idx_task_project_links_project ON task_project_links(project_id);
