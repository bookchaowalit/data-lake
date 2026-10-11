-- 043_portfolio_contexts_and_personal_roles.sql
-- Separate professional capability roles from personal identities and work contexts.

CREATE TABLE IF NOT EXISTS portfolio_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    context_type TEXT NOT NULL CHECK(context_type IN (
        'personal', 'hobby', 'learning', 'freelance', 'startup', 'venture',
        'client_engagement', 'internal', 'business_system', 'workspace',
        'role_capability', 'unclassified'
    )),
    scope TEXT NOT NULL DEFAULT 'personal' CHECK(scope IN ('personal', 'professional', 'client', 'mixed')),
    parent_context_id INTEGER REFERENCES portfolio_contexts(id) ON DELETE SET NULL,
    description TEXT,
    source_path TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('planned', 'active', 'paused', 'completed', 'archived')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personal_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    source_path TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('planned', 'active', 'paused', 'retired')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goal_context_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    context_id INTEGER NOT NULL REFERENCES portfolio_contexts(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'primary' CHECK(relation_type IN ('primary', 'supporting')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(goal_id, context_id)
);

CREATE TABLE IF NOT EXISTS project_context_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    context_id INTEGER NOT NULL REFERENCES portfolio_contexts(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'primary' CHECK(relation_type IN ('primary', 'supporting')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, context_id)
);

CREATE TABLE IF NOT EXISTS task_context_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    context_id INTEGER NOT NULL REFERENCES portfolio_contexts(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'primary' CHECK(relation_type IN ('primary', 'supporting')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, context_id)
);

CREATE TABLE IF NOT EXISTS personal_role_context_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personal_role_id INTEGER NOT NULL REFERENCES personal_roles(id) ON DELETE CASCADE,
    context_id INTEGER NOT NULL REFERENCES portfolio_contexts(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'belongs_to' CHECK(relation_type IN ('belongs_to', 'supports')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personal_role_id, context_id)
);

CREATE TABLE IF NOT EXISTS personal_role_goal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personal_role_id INTEGER NOT NULL REFERENCES personal_roles(id) ON DELETE CASCADE,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'primary' CHECK(link_type IN ('primary', 'supporting')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personal_role_id, goal_id)
);

CREATE TABLE IF NOT EXISTS personal_role_project_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personal_role_id INTEGER NOT NULL REFERENCES personal_roles(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'primary' CHECK(link_type IN ('primary', 'supporting')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personal_role_id, project_id)
);

CREATE TABLE IF NOT EXISTS personal_role_task_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personal_role_id INTEGER NOT NULL REFERENCES personal_roles(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'primary' CHECK(link_type IN ('primary', 'supporting')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personal_role_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_contexts_parent ON portfolio_contexts(parent_context_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_contexts_type ON portfolio_contexts(context_type, scope);
CREATE INDEX IF NOT EXISTS idx_personal_roles_category ON personal_roles(category);
CREATE INDEX IF NOT EXISTS idx_goal_context_links_goal ON goal_context_links(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_context_links_context ON goal_context_links(context_id);
CREATE INDEX IF NOT EXISTS idx_project_context_links_project ON project_context_links(project_id);
CREATE INDEX IF NOT EXISTS idx_project_context_links_context ON project_context_links(context_id);
CREATE INDEX IF NOT EXISTS idx_task_context_links_task ON task_context_links(task_id);
CREATE INDEX IF NOT EXISTS idx_task_context_links_context ON task_context_links(context_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_context_links_role ON personal_role_context_links(personal_role_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_context_links_context ON personal_role_context_links(context_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_goal_links_role ON personal_role_goal_links(personal_role_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_goal_links_goal ON personal_role_goal_links(goal_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_project_links_role ON personal_role_project_links(personal_role_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_project_links_project ON personal_role_project_links(project_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_task_links_role ON personal_role_task_links(personal_role_id);
CREATE INDEX IF NOT EXISTS idx_personal_role_task_links_task ON personal_role_task_links(task_id);
