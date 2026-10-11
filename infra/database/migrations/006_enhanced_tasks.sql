-- Migration 006: Enhanced Task Management
-- Adds: reminders, dependencies, recurring tasks, time tracking, templates

-- =====================================================
-- TASK REMINDERS: Track when to remind about tasks
-- =====================================================
ALTER TABLE tasks ADD COLUMN reminder_at DATETIME;
ALTER TABLE tasks ADD COLUMN reminder_sent BOOLEAN DEFAULT 0;
ALTER TABLE tasks ADD COLUMN reminder_channels TEXT; -- JSON array: ["email", "slack", "push", "desktop"]

-- =====================================================
-- TASK TIME TRACKING: Estimated and actual time
-- =====================================================
ALTER TABLE tasks ADD COLUMN estimated_minutes INTEGER;
ALTER TABLE tasks ADD COLUMN actual_minutes INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN started_at DATETIME;

-- =====================================================
-- TASK DEPENDENCIES: Many-to-many task dependencies
-- =====================================================
CREATE TABLE IF NOT EXISTS task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dependency_type TEXT CHECK(dependency_type IN ('finish_to_start', 'start_to_start', 'finish_to_finish', 'start_to_finish')) DEFAULT 'finish_to_start',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, depends_on_task_id)
);

CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_depends_on ON task_dependencies(depends_on_task_id);

-- =====================================================
-- RECURRING TASK TEMPLATES: For auto-generating recurring tasks
-- =====================================================
ALTER TABLE tasks ADD COLUMN recurrence_rule TEXT; -- RRULE format: FREQ=DAILY;INTERVAL=1
ALTER TABLE tasks ADD COLUMN parent_recurring_id INTEGER REFERENCES tasks(id);
ALTER TABLE tasks ADD COLUMN is_recurring_instance BOOLEAN DEFAULT 0;
ALTER TABLE tasks ADD COLUMN recurrence_occurrence INTEGER; -- which occurrence (1, 2, 3...)

CREATE INDEX IF NOT EXISTS idx_tasks_parent_recurring ON tasks(parent_recurring_id);
CREATE INDEX IF NOT EXISTS idx_tasks_recurrence ON tasks(is_recurring_instance);

-- =====================================================
-- TASK TEMPLATES: Reusable task templates
-- =====================================================
CREATE TABLE IF NOT EXISTS task_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Template content
    title_template TEXT NOT NULL,
    description_template TEXT,
    default_priority INTEGER DEFAULT 3 CHECK(default_priority >= 1 AND default_priority <= 5),
    default_category TEXT,
    default_tags TEXT, -- JSON array
    default_estimated_minutes INTEGER,
    
    -- Recurrence preset
    default_recurrence TEXT, -- daily, weekly, monthly, yearly, custom
    
    -- Organization
    project TEXT,
    tags TEXT, -- JSON array for template categorization
    
    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    last_used_at DATETIME,
    
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_templates_active ON task_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_task_templates_usage ON task_templates(usage_count DESC);

-- =====================================================
-- TASK COMMENTS: Collaboration and notes
-- =====================================================
CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    
    author TEXT, -- user/system identifier
    comment_type TEXT CHECK(comment_type IN ('comment', 'status_change', 'priority_change', 'assignment', 'system')) DEFAULT 'comment',
    content TEXT NOT NULL,
    
    -- For change tracking
    old_value TEXT,
    new_value TEXT,
    
    -- Sync
    external_comment_id TEXT,
    external_source TEXT,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_id);
CREATE INDEX IF NOT EXISTS idx_task_comments_date ON task_comments(created_at);

-- =====================================================
-- TASK ATTACHMENTS: Files linked to tasks
-- =====================================================
CREATE TABLE IF NOT EXISTS task_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    
    -- Metadata
    description TEXT,
    uploaded_by TEXT,
    
    -- Sync
    external_attachment_id TEXT,
    external_source TEXT,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_attachments_task ON task_attachments(task_id);

-- =====================================================
-- TASK ASSIGNMENTS: For collaboration (future use)
-- =====================================================
CREATE TABLE IF NOT EXISTS task_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    
    assignee_type TEXT CHECK(assignee_type IN ('user', 'team', 'role')) DEFAULT 'user',
    assignee_id TEXT NOT NULL, -- user ID, team ID, or role name
    assignee_name TEXT,
    
    assignment_type TEXT CHECK(assignment_type IN ('assigned', 'cc', 'viewer')) DEFAULT 'assigned',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, assignee_id, assignment_type)
);

CREATE INDEX IF NOT EXISTS idx_task_assignments_task ON task_assignments(task_id);
CREATE INDEX IF NOT EXISTS idx_task_assignments_assignee ON task_assignments(assignee_id);

-- =====================================================
-- TASK AUDIT LOG: Track all changes for security
-- =====================================================
CREATE TABLE IF NOT EXISTS task_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    
    action TEXT NOT NULL, -- create, update, delete, sync, status_change, etc.
    actor TEXT, -- user/system that performed action
    source TEXT, -- local, leantime, todoist, jira, notion
    
    -- What changed
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    
    -- Context
    ip_address TEXT,
    user_agent TEXT,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_audit_task ON task_audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_task_audit_action ON task_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_task_audit_date ON task_audit_log(created_at);

-- =====================================================
-- VIEWS: Saved task views/filters
-- =====================================================
CREATE TABLE IF NOT EXISTS task_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Filter criteria as JSON
    filter_criteria TEXT NOT NULL, -- JSON: {status: [...], priority: [...], project: [...], tags: [...], date_range: {...}}
    sort_by TEXT, -- field name
    sort_order TEXT CHECK(sort_order IN ('asc', 'desc')) DEFAULT 'asc',
    group_by TEXT, -- field name
    
    -- Display
    view_type TEXT CHECK(view_type IN ('list', 'board', 'calendar', 'timeline')) DEFAULT 'list',
    columns TEXT, -- JSON array of fields to show
    
    -- Organization
    is_default BOOLEAN DEFAULT 0,
    is_shared BOOLEAN DEFAULT 0,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_views_default ON task_views(is_default);

-- =====================================================
-- NOTIFICATION RULES: Custom alert rules
-- =====================================================
CREATE TABLE IF NOT EXISTS task_notification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Trigger conditions (JSON)
    trigger_conditions TEXT NOT NULL, -- JSON: {due_soon: hours, priority_changed: bool, status_changed: [...], assigned_to_me: bool}
    
    -- Notification channels
    channels TEXT NOT NULL, -- JSON array: ["email", "slack", "push", "desktop"]
    
    -- Recipient
    recipient_type TEXT CHECK(recipient_type IN ('self', 'assignee', 'custom')) DEFAULT 'self',
    recipient_value TEXT, -- email, slack channel, etc.
    
    -- Status
    is_active BOOLEAN DEFAULT 1,
    last_triggered_at DATETIME,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notification_rules_active ON task_notification_rules(is_active);

-- Record migration
INSERT INTO schema_migrations (version, description) VALUES ('006', 'Enhanced task management: reminders, dependencies, recurring, templates, comments, attachments, assignments, audit, views, notifications');
