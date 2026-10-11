-- Retire the task tables from the control plane (owner decision 2026-10-09).
-- Tasks live in the empire-platform Tasks API (Neon). Tables that referenced
-- tasks(id) keep every row; task_id becomes a soft reference to the API task
-- number. Generated from the live schema by the retirement script; reviewed.
PRAGMA foreign_keys = OFF;
BEGIN;

-- custom_field_values
CREATE TABLE custom_field_values__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (field_id) REFERENCES custom_fields(id) ON DELETE CASCADE,
    UNIQUE(task_id, field_id)
);
INSERT INTO custom_field_values__retire_new ("id", "task_id", "field_id", "value", "updated_at") SELECT "id", "task_id", "field_id", "value", "updated_at" FROM custom_field_values;
DROP TABLE custom_field_values;
ALTER TABLE custom_field_values__retire_new RENAME TO custom_field_values;

-- decision_reviews
CREATE TABLE decision_reviews__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decision_records(id) ON DELETE CASCADE,
    task_id INTEGER,
    due_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'skipped')),
    reviewer TEXT,
    outcome TEXT,
    notes TEXT,
    reviewed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(decision_id, due_date)
);
INSERT INTO decision_reviews__retire_new ("id", "decision_id", "task_id", "due_date", "status", "reviewer", "outcome", "notes", "reviewed_at", "created_at", "updated_at") SELECT "id", "decision_id", "task_id", "due_date", "status", "reviewer", "outcome", "notes", "reviewed_at", "created_at", "updated_at" FROM decision_reviews;
DROP TABLE decision_reviews;
ALTER TABLE decision_reviews__retire_new RENAME TO decision_reviews;
CREATE INDEX idx_decision_reviews_decision
    ON decision_reviews(decision_id, due_date DESC);
CREATE INDEX idx_decision_reviews_due
    ON decision_reviews(status, due_date);

-- notification_log
CREATE TABLE notification_log__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER REFERENCES notification_rules(id),
    task_id INTEGER,
    -- Notification content
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    -- matches rule_type
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
    metadata TEXT /* JSON for extra data */,
    delivered_at DATETIME,
    delivery_channel TEXT,
    delivery_error TEXT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0
);
INSERT INTO notification_log__retire_new ("id", "rule_id", "task_id", "title", "message", "notification_type", "severity", "channel", "task_title", "task_status", "task_priority", "task_due_date", "task_project", "sent_at", "read_at", "dismissed_at", "metadata", "delivered_at", "delivery_channel", "delivery_error", "delivery_attempts") SELECT "id", "rule_id", "task_id", "title", "message", "notification_type", "severity", "channel", "task_title", "task_status", "task_priority", "task_due_date", "task_project", "sent_at", "read_at", "dismissed_at", "metadata", "delivered_at", "delivery_channel", "delivery_error", "delivery_attempts" FROM notification_log;
DROP TABLE notification_log;
ALTER TABLE notification_log__retire_new RENAME TO notification_log;
CREATE INDEX idx_notif_log_rule ON notification_log(rule_id);
CREATE INDEX idx_notif_log_task ON notification_log(task_id);
CREATE INDEX idx_notif_log_sent ON notification_log(sent_at DESC);
CREATE INDEX idx_notif_log_unread ON notification_log(read_at) WHERE read_at IS NULL;
CREATE INDEX idx_notification_log_delivery
    ON notification_log (notification_type, delivered_at, id);

-- notifications
CREATE TABLE notifications__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    -- console, line, slack, email
    message TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER DEFAULT 0
);
INSERT INTO notifications__retire_new ("id", "task_id", "channel", "message", "sent_at", "is_read") SELECT "id", "task_id", "channel", "message", "sent_at", "is_read" FROM notifications;
DROP TABLE notifications;
ALTER TABLE notifications__retire_new RENAME TO notifications;
CREATE INDEX idx_notif_task ON notifications(task_id);
CREATE INDEX idx_notif_sent ON notifications(sent_at DESC);
CREATE INDEX idx_notif_unread ON notifications(is_read) WHERE is_read = 0;

-- operating_cycle_tasks
CREATE TABLE operating_cycle_tasks__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES "operating_cycles"(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL,
    commitment_type TEXT NOT NULL DEFAULT 'committed'
        CHECK(commitment_type IN ('committed', 'stretch', 'carried_over', 'dropped')),
    estimate_minutes INTEGER CHECK(estimate_minutes IS NULL OR estimate_minutes >= 0),
    evidence_required INTEGER NOT NULL DEFAULT 1 CHECK(evidence_required IN (0, 1)),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cycle_id, task_id)
);
INSERT INTO operating_cycle_tasks__retire_new ("id", "cycle_id", "task_id", "commitment_type", "estimate_minutes", "evidence_required", "notes", "created_at", "updated_at") SELECT "id", "cycle_id", "task_id", "commitment_type", "estimate_minutes", "evidence_required", "notes", "created_at", "updated_at" FROM operating_cycle_tasks;
DROP TABLE operating_cycle_tasks;
ALTER TABLE operating_cycle_tasks__retire_new RENAME TO operating_cycle_tasks;
CREATE INDEX idx_operating_cycle_tasks_task
    ON operating_cycle_tasks(task_id, cycle_id);

-- personal_role_task_links
CREATE TABLE personal_role_task_links__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personal_role_id INTEGER NOT NULL REFERENCES personal_roles(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'primary' CHECK(link_type IN ('primary', 'supporting')),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(personal_role_id, task_id)
);
INSERT INTO personal_role_task_links__retire_new ("id", "personal_role_id", "task_id", "link_type", "source", "created_at", "updated_at") SELECT "id", "personal_role_id", "task_id", "link_type", "source", "created_at", "updated_at" FROM personal_role_task_links;
DROP TABLE personal_role_task_links;
ALTER TABLE personal_role_task_links__retire_new RENAME TO personal_role_task_links;
CREATE INDEX idx_personal_role_task_links_role ON personal_role_task_links(personal_role_id);
CREATE INDEX idx_personal_role_task_links_task ON personal_role_task_links(task_id);

-- sync_queue
CREATE TABLE sync_queue__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL CHECK(operation IN ('create','update','delete')),
    source TEXT NOT NULL,
    task_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_attempt_at TEXT
);
INSERT INTO sync_queue__retire_new ("id", "operation", "source", "task_id", "payload", "attempts", "last_error", "created_at", "last_attempt_at") SELECT "id", "operation", "source", "task_id", "payload", "attempts", "last_error", "created_at", "last_attempt_at" FROM sync_queue;
DROP TABLE sync_queue;
ALTER TABLE sync_queue__retire_new RENAME TO sync_queue;

-- task_audit_log
CREATE TABLE task_audit_log__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    action TEXT NOT NULL,
    -- create, update, delete, sync, status_change, etc.
    actor TEXT,
    -- user/system that performed action
    source TEXT,
    -- local, leantime, todoist, jira, notion
    
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO task_audit_log__retire_new ("id", "task_id", "action", "actor", "source", "field_name", "old_value", "new_value", "ip_address", "user_agent", "created_at") SELECT "id", "task_id", "action", "actor", "source", "field_name", "old_value", "new_value", "ip_address", "user_agent", "created_at" FROM task_audit_log;
DROP TABLE task_audit_log;
ALTER TABLE task_audit_log__retire_new RENAME TO task_audit_log;
CREATE INDEX idx_task_audit_task ON task_audit_log(task_id);
CREATE INDEX idx_task_audit_action ON task_audit_log(action);
CREATE INDEX idx_task_audit_date ON task_audit_log(created_at);

-- time_entries
CREATE TABLE time_entries__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    -- Time data
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    duration_seconds INTEGER,
    -- Calculated on stop
    
    -- Source
    source TEXT DEFAULT 'manual',
    -- manual, pomodoro, auto
    notes TEXT,
    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO time_entries__retire_new ("id", "task_id", "started_at", "ended_at", "duration_seconds", "source", "notes", "created_at", "updated_at") SELECT "id", "task_id", "started_at", "ended_at", "duration_seconds", "source", "notes", "created_at", "updated_at" FROM time_entries;
DROP TABLE time_entries;
ALTER TABLE time_entries__retire_new RENAME TO time_entries;
CREATE INDEX idx_time_task ON time_entries(task_id);
CREATE INDEX idx_time_started ON time_entries(started_at DESC);
CREATE INDEX idx_time_active ON time_entries(ended_at) WHERE ended_at IS NULL;

-- work_item_task_links
CREATE TABLE work_item_task_links__retire_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id INTEGER NOT NULL REFERENCES portfolio_work_items(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'implements' CHECK(relation_type IN ('implements', 'supports')),
    weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(work_item_id, task_id)
);
INSERT INTO work_item_task_links__retire_new ("id", "work_item_id", "task_id", "relation_type", "weight", "created_at") SELECT "id", "work_item_id", "task_id", "relation_type", "weight", "created_at" FROM work_item_task_links;
DROP TABLE work_item_task_links;
ALTER TABLE work_item_task_links__retire_new RENAME TO work_item_task_links;
CREATE INDEX idx_work_item_task_links_item ON work_item_task_links(work_item_id);
CREATE INDEX idx_work_item_task_links_task ON work_item_task_links(task_id);

-- the task cell tables themselves (data is in the Tasks API; backups kept)
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS task_assignments;
DROP TABLE IF EXISTS task_goal_links;
DROP TABLE IF EXISTS task_project_links;
DROP TABLE IF EXISTS task_context_links;
DROP TABLE IF EXISTS task_skill_links;
DROP TABLE IF EXISTS task_role_suggestions;
DROP TABLE IF EXISTS task_types;
DROP TABLE IF EXISTS task_dependencies;
DROP TABLE IF EXISTS task_comments;
DROP TABLE IF EXISTS task_attachments;
COMMIT;
PRAGMA foreign_keys = ON;
