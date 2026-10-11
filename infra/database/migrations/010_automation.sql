-- Migration 010: Automation System
-- Adds: automation rules, workflow pipelines, cron jobs

-- =====================================================
-- AUTOMATION RULES: If-then triggers
-- =====================================================
CREATE TABLE IF NOT EXISTS automation_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Trigger condition (JSON)
    -- Examples:
    --   {"type": "status_change", "from": "todo", "to": "in_progress"}
    --   {"type": "due_date_approaching", "hours": 24}
    --   {"type": "priority_changed", "to": 1}
    --   {"type": "task_created", "project": "DCS"}
    --   {"type": "task_completed", "project": null}
    trigger TEXT NOT NULL,
    
    -- Action to take (JSON)
    -- Examples:
    --   {"type": "update_status", "status": "in_progress"}
    --   {"type": "add_tag", "tag": "urgent"}
    --   {"type": "send_notification", "message": "Task is due soon"}
    --   {"type": "create_subtask", "title": "Review: {parent_title}"}
    --   {"type": "move_project", "project": "Review"}
    action TEXT NOT NULL,
    
    -- Scope
    project_filter TEXT,       -- NULL = all projects
    priority_filter INTEGER,   -- NULL = all priorities
    category_filter TEXT,      -- NULL = all categories
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    execution_count INTEGER DEFAULT 0,
    last_executed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_auto_rules_active ON automation_rules(is_active);

-- =====================================================
-- WORKFLOW PIPELINES: Multi-step batch operations
-- =====================================================
CREATE TABLE IF NOT EXISTS workflow_pipelines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Steps (JSON array of actions)
    -- [
    --   {"step": 1, "action": "filter", "criteria": {"status": "todo", "project": "DCS"}},
    --   {"step": 2, "action": "update_status", "status": "in_progress"},
    --   {"step": 3, "action": "add_tag", "tag": "batch-processed"}
    -- ]
    steps TEXT NOT NULL,
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    run_count INTEGER DEFAULT 0,
    last_run_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- AUTOMATION LOG: Track what was executed
-- =====================================================
CREATE TABLE IF NOT EXISTS automation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER REFERENCES automation_rules(id),
    pipeline_id INTEGER REFERENCES workflow_pipelines(id),
    
    -- What happened
    action_type TEXT NOT NULL,  -- 'rule', 'pipeline', 'cron'
    description TEXT NOT NULL,
    
    -- Affected tasks (JSON array of task IDs)
    affected_tasks TEXT,
    affected_count INTEGER DEFAULT 0,
    
    -- Result
    success BOOLEAN DEFAULT 1,
    error_message TEXT,
    
    -- Metadata
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_auto_log_rule ON automation_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_auto_log_exec ON automation_log(executed_at DESC);

-- =====================================================
-- CRON JOBS: Scheduled automation tasks
-- =====================================================
CREATE TABLE IF NOT EXISTS cron_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Schedule (cron expression or simple interval)
    schedule TEXT NOT NULL,  -- e.g., "0 9 * * *" or "daily", "hourly", "weekly"
    
    -- What to run
    job_type TEXT NOT NULL CHECK(job_type IN (
        'sync',              -- Full sync
        'smart_sync',        -- Smart sync
        'generate_tasks',    -- Generate recurring tasks
        'check_reminders',   -- Check reminders
        'check_notifications', -- Check notification rules
        'take_snapshot',     -- Daily snapshot
        'auto_archive',      -- Auto-archive old tasks
        'run_pipeline',      -- Run a workflow pipeline
        'update_goals'       -- Update productivity goals
    )),
    
    -- Parameters (JSON)
    params TEXT DEFAULT '{}',
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    last_run_at DATETIME,
    next_run_at DATETIME,
    last_status TEXT DEFAULT 'pending',  -- pending, running, success, failed
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cron_active ON cron_jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_cron_next ON cron_jobs(next_run_at);

-- =====================================================
-- SEED DEFAULT AUTOMATION RULES
-- =====================================================
INSERT OR IGNORE INTO automation_rules (name, description, trigger, action)
VALUES 
    ('Auto-start on due date', 'When a task becomes due today, auto-move to in_progress',
     '{"type": "due_date_approaching", "hours": 0}',
     '{"type": "update_status", "status": "in_progress"}'),
    ('High priority alert', 'When a P1 task is created, tag it urgent',
     '{"type": "task_created", "priority": 1}',
     '{"type": "add_tag", "tag": "urgent"}'),
    ('Completion celebration', 'When a P1-P2 task is completed, log it',
     '{"type": "task_completed", "max_priority": 2}',
     '{"type": "send_notification", "message": "High priority task completed!"}');

-- =====================================================
-- SEED DEFAULT WORKFLOW PIPELINES
-- =====================================================
INSERT OR IGNORE INTO workflow_pipelines (name, description, steps)
VALUES 
    ('Morning Review', 'Review and prioritize today tasks',
     '[{"step":1,"action":"filter","criteria":{"status":"todo","has_due_date":true}},{"step":2,"action":"sort","by":"priority","order":"asc"},{"step":3,"action":"report","format":"summary"}]'),
    ('Weekly Cleanup', 'Archive completed tasks and check stale items',
     '[{"step":1,"action":"auto_archive","days":30},{"step":2,"action":"filter","criteria":{"status":"in_progress","stale_days":7}},{"step":3,"action":"report","format":"stale_warning"}]'),
    ('Sprint Close', 'Close out completed sprint tasks',
     '[{"step":1,"action":"filter","criteria":{"status":"done"}},{"step":2,"action":"add_tag","tag":"sprint-closed"},{"step":3,"action":"report","format":"completion_summary"}]');

-- =====================================================
-- SEED DEFAULT CRON JOBS
-- =====================================================
INSERT OR IGNORE INTO cron_jobs (name, description, schedule, job_type, params)
VALUES 
    ('Daily Snapshot', 'Capture daily task metrics', 'daily', 'take_snapshot', '{}'),
    ('Morning Sync', 'Sync all sources at start of day', '0 8 * * *', 'smart_sync', '{}'),
    ('Generate Recurring', 'Create recurring task instances', '0 6 * * *', 'generate_tasks', '{}'),
    ('Check Notifications', 'Run notification checks', '0 */2 * * *', 'check_notifications', '{}'),
    ('Update Goals', 'Refresh productivity goal progress', '0 20 * * *', 'update_goals', '{}'),
    ('Auto Archive', 'Archive old completed tasks', 'weekly', 'auto_archive', '{"days": 30}');
