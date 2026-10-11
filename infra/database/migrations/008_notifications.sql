-- Migration 008: Notification System
-- Adds: notification rules, notification log, notification preferences

-- =====================================================
-- NOTIFICATION RULES: When to send notifications
-- =====================================================
CREATE TABLE IF NOT EXISTS notification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    rule_type TEXT NOT NULL CHECK(rule_type IN (
        'overdue',           -- Task past due_date
        'due_soon',          -- Task due within N hours
        'high_priority',     -- Priority 1-2 tasks
        'stale',             -- No updates for N days
        'blocked',           -- Tasks in blocked status
        'status_change',     -- Task status changed
        'reminder'           -- Manual reminder_at reached
    )),
    
    -- Rule configuration (JSON)
    -- Examples:
    --   overdue: {}
    --   due_soon: {"hours": 24}
    --   high_priority: {"max_priority": 2}
    --   stale: {"days": 7}
    --   blocked: {}
    --   reminder: {}
    config TEXT DEFAULT '{}',
    
    -- Channels to notify: JSON array ["console", "telegram", "email", "desktop"]
    channels TEXT DEFAULT '["console"]',
    
    -- Filtering
    project_filter TEXT,         -- NULL = all projects, or specific project name
    category_filter TEXT,        -- NULL = all categories
    priority_filter INTEGER,     -- NULL = all, or max priority to include
    status_filter TEXT,          -- JSON array of statuses to include, NULL = active only
    
    -- Scheduling
    check_interval_minutes INTEGER DEFAULT 60,  -- How often to check this rule
    last_checked_at DATETIME,
    last_triggered_at DATETIME,
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notif_rules_active ON notification_rules(is_active);
CREATE INDEX IF NOT EXISTS idx_notif_rules_type ON notification_rules(rule_type);

-- =====================================================
-- NOTIFICATION LOG: History of sent notifications
-- =====================================================
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER REFERENCES notification_rules(id),
    task_id INTEGER REFERENCES tasks(id),
    
    -- Notification content
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    notification_type TEXT NOT NULL,  -- matches rule_type
    severity TEXT DEFAULT 'info' CHECK(severity IN ('info', 'warning', 'critical', 'success')),
    
    -- Channel used
    channel TEXT NOT NULL DEFAULT 'console',
    
    -- Task snapshot at notification time
    task_title TEXT,
    task_status TEXT,
    task_priority INTEGER,
    task_due_date TEXT,
    task_project TEXT,
    
    -- Delivery tracking
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    read_at DATETIME,
    dismissed_at DATETIME,
    
    -- Metadata
    metadata TEXT  -- JSON for extra data
);

CREATE INDEX IF NOT EXISTS idx_notif_log_rule ON notification_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_notif_log_task ON notification_log(task_id);
CREATE INDEX IF NOT EXISTS idx_notif_log_sent ON notification_log(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_log_unread ON notification_log(read_at) WHERE read_at IS NULL;

-- =====================================================
-- SEED DEFAULT NOTIFICATION RULES
-- =====================================================
INSERT OR IGNORE INTO notification_rules (name, description, rule_type, config, channels, check_interval_minutes)
VALUES 
    ('Overdue Tasks', 'Notify when tasks are past their due date', 'overdue', '{}', '["console"]', 60),
    ('Due Soon (24h)', 'Notify when tasks are due within 24 hours', 'due_soon', '{"hours": 24}', '["console"]', 120),
    ('High Priority Alert', 'Notify for priority 1-2 tasks that are active', 'high_priority', '{"max_priority": 2}', '["console"]', 180),
    ('Stale Tasks', 'Notify when active tasks have no updates for 7 days', 'stale', '{"days": 7}', '["console"]', 1440),
    ('Blocked Tasks', 'Notify when tasks are in blocked status', 'blocked', '{}', '["console"]', 60);
