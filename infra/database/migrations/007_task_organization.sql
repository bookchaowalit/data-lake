-- Migration 007: Task Organization
-- Adds: categories hierarchy, project enhancements, task archiving
-- Note: projects table already exists — we add missing columns

-- =====================================================
-- CATEGORIES: Hierarchical category system
-- =====================================================
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    color TEXT,
    icon TEXT,
    
    -- Hierarchy
    parent_id INTEGER REFERENCES categories(id),
    
    -- Organization
    sort_order INTEGER DEFAULT 0,
    
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_categories_active ON categories(is_active);

-- =====================================================
-- PROJECT ENHANCEMENTS: Add missing columns to existing projects table
-- =====================================================
-- Add color column if not exists
ALTER TABLE projects ADD COLUMN color TEXT;
ALTER TABLE projects ADD COLUMN parent_project_id INTEGER REFERENCES projects(id);
ALTER TABLE projects ADD COLUMN task_count INTEGER DEFAULT 0;
ALTER TABLE projects ADD COLUMN completed_count INTEGER DEFAULT 0;
ALTER TABLE projects ADD COLUMN archived_at DATETIME;

CREATE INDEX IF NOT EXISTS idx_projects_parent ON projects(parent_project_id);

-- =====================================================
-- TASK ARCHIVE: Add archiving columns to tasks
-- =====================================================
ALTER TABLE tasks ADD COLUMN archived_at DATETIME;
ALTER TABLE tasks ADD COLUMN archive_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_tasks_archived ON tasks(archived_at);

-- =====================================================
-- Seed project task counts from existing task data
-- =====================================================
UPDATE projects SET task_count = (
    SELECT COUNT(*) FROM tasks WHERE tasks.project = projects.name
);

-- Record migration
INSERT INTO schema_migrations (version, description) VALUES ('007', 'Task organization: categories hierarchy, project enhancements, task archiving');
