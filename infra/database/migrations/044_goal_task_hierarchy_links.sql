-- 044_goal_task_hierarchy_links.sql
-- Bridge the legacy goal_tasks projection into the continuous work hierarchy.

CREATE TABLE IF NOT EXISTS goal_task_project_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_task_id INTEGER NOT NULL REFERENCES goal_tasks(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'delivery' CHECK(relation_type IN ('delivery', 'supporting')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(goal_task_id, project_id)
);

CREATE TABLE IF NOT EXISTS work_item_goal_task_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER NOT NULL REFERENCES portfolio_work_items(id) ON DELETE CASCADE,
    goal_task_id INTEGER NOT NULL REFERENCES goal_tasks(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'implements' CHECK(relation_type IN ('implements', 'supports')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(work_item_id, goal_task_id)
);

CREATE INDEX IF NOT EXISTS idx_goal_task_project_links_goal_task ON goal_task_project_links(goal_task_id);
CREATE INDEX IF NOT EXISTS idx_goal_task_project_links_project ON goal_task_project_links(project_id);
CREATE INDEX IF NOT EXISTS idx_work_item_goal_task_links_item ON work_item_goal_task_links(work_item_id);
CREATE INDEX IF NOT EXISTS idx_work_item_goal_task_links_goal_task ON work_item_goal_task_links(goal_task_id);
