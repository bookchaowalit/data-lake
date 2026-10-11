-- Solo Empire Database Schema
-- Regenerated from the live database via:
--   python3 infra/scripts/db/migrate_db.py --dump-schema
-- Do not hand-edit table definitions here after running migrations --
-- run --dump-schema again instead, or this file will drift out of sync.

-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- profile (table)
CREATE TABLE profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    title TEXT,
    bio TEXT,
    tagline TEXT,
    location TEXT,
    email TEXT,
    website TEXT,
    avatar_url TEXT,
    header_image_url TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    birth_date DATE
);

-- social_links (table)
CREATE TABLE social_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    -- github, linkedin, twitter, youtube, etc.
    url TEXT NOT NULL,
    username TEXT,
    display_name TEXT,
    description TEXT,
    is_primary BOOLEAN DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- sync_log (table)
CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- What was synced
    entity_type TEXT NOT NULL,
    -- profile, social_links, content, etc.
    entity_id INTEGER,
    -- Target
    target_system TEXT NOT NULL,
    -- landing_page, twitter, linkedin, etc.
    target_id TEXT,
    -- ID in target system

    -- Result
    status TEXT CHECK(status IN ('success', 'failed', 'partial')) NOT NULL,
    error_message TEXT,
    -- Data
    data_synced TEXT,
    -- JSON of what was sent
    response TEXT,
    -- JSON of response

    synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- repo_metrics (table)
CREATE TABLE repo_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT NOT NULL,
    metric_date DATE NOT NULL,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    watchers INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    size_kb INTEGER DEFAULT 0,
    commits_count INTEGER DEFAULT 0,
    last_commit_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo_name, metric_date)
);

-- calendar_events (table)
CREATE TABLE calendar_events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'google',
    title TEXT NOT NULL,
    description TEXT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    location TEXT,
    attendees TEXT,
    is_all_day INTEGER DEFAULT 0,
    recurrence_rule TEXT,
    color TEXT,
    status TEXT DEFAULT 'confirmed',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- emails (table)
CREATE TABLE emails (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'gmail',
    from_address TEXT NOT NULL,
    from_name TEXT,
    to_addresses TEXT,
    subject TEXT,
    snippet TEXT,
    received_at DATETIME NOT NULL,
    labels TEXT,
    is_read INTEGER DEFAULT 0,
    is_important INTEGER DEFAULT 0,
    has_attachment INTEGER DEFAULT 0,
    thread_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    pipeline_status TEXT DEFAULT 'pending',
    pipeline_processed_at DATETIME,
    pipeline_error TEXT,
    category TEXT DEFAULT 'unclassified',
    lake_event_id TEXT,
    lake_run_id TEXT,
    lake_snapshot_id TEXT,
    lake_table TEXT,
    lake_raw_object_key TEXT
);

-- external_tasks (table)
CREATE TABLE external_tasks (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    due_date DATE,
    priority INTEGER DEFAULT 3,
    status TEXT DEFAULT 'pending',
    project TEXT,
    tags TEXT,
    url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- schema_migrations (table)
CREATE TABLE schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT DEFAULT (datetime('now')),
    description TEXT
);

-- task_templates (table)
CREATE TABLE task_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    title_template TEXT NOT NULL,
    description_template TEXT,
    default_priority INTEGER DEFAULT 3 CHECK(default_priority >= 1 AND default_priority <= 5),
    default_category TEXT,
    default_tags TEXT,
    -- JSON array
    default_estimated_minutes INTEGER,
    default_recurrence TEXT,
    -- daily, weekly, monthly, yearly, custom
    
    project TEXT,
    tags TEXT,
    -- JSON array for template categorization
    
    usage_count INTEGER DEFAULT 0,
    last_used_at DATETIME,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- task_views (table)
CREATE TABLE task_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    filter_criteria TEXT NOT NULL,
    -- JSON: {status: [...], priority: [...], project: [...], tags: [...], date_range: {...}}
    sort_by TEXT,
    -- field name
    sort_order TEXT CHECK(sort_order IN ('asc', 'desc')) DEFAULT 'asc',
    group_by TEXT,
    -- field name
    
    view_type TEXT CHECK(view_type IN ('list', 'board', 'calendar', 'timeline')) DEFAULT 'list',
    columns TEXT,
    -- JSON array of fields to show
    
    is_default BOOLEAN DEFAULT 0,
    is_shared BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- task_notification_rules (table)
CREATE TABLE task_notification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    trigger_conditions TEXT NOT NULL,
    -- JSON: {due_soon: hours, priority_changed: bool, status_changed: [...], assigned_to_me: bool}
    
    channels TEXT NOT NULL,
    -- JSON array: ["email", "slack", "push", "desktop"]
    
    recipient_type TEXT CHECK(recipient_type IN ('self', 'assignee', 'custom')) DEFAULT 'self',
    recipient_value TEXT,
    -- email, slack channel, etc.
    
    is_active BOOLEAN DEFAULT 1,
    last_triggered_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- webhook_log (table)
CREATE TABLE webhook_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    external_id TEXT,
    payload TEXT NOT NULL,
    processed INTEGER DEFAULT 0,
    received_at TEXT DEFAULT (datetime('now'))
);

-- categories (table)
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    color TEXT,
    icon TEXT,
    parent_id INTEGER REFERENCES categories(id),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- daily_snapshots (table)
CREATE TABLE daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL UNIQUE,
    -- Task counts
    total_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    active_tasks INTEGER DEFAULT 0,
    overdue_tasks INTEGER DEFAULT 0,
    blocked_tasks INTEGER DEFAULT 0,
    -- Completions this day
    completed_today INTEGER DEFAULT 0,
    created_today INTEGER DEFAULT 0,
    -- Time tracking
    total_time_seconds INTEGER DEFAULT 0,
    -- By project (JSON)
    project_breakdown TEXT,
    -- {"Project A": 5, "Project B": 3}
    
    -- By priority (JSON)
    priority_breakdown TEXT,
    -- {"1": 2, "2": 5, "3": 10}
    
    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- collaborators (table)
CREATE TABLE collaborators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    role TEXT DEFAULT 'member' CHECK(role IN ('owner', 'admin', 'member', 'viewer')),
    avatar_url TEXT,
    -- State
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- shared_lists (table)
CREATE TABLE shared_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    owner_id INTEGER REFERENCES collaborators(id),
    -- Access
    visibility TEXT DEFAULT 'private' CHECK(visibility IN ('private', 'team', 'public')),
    -- Filter criteria (JSON) — dynamic lists
    -- e.g. {"project": "DCS", "status": ["todo", "in_progress"], "priority": [1, 2]}
    filter_criteria TEXT,
    -- Manual task list (JSON array of task IDs) — for static lists
    task_ids TEXT DEFAULT '[]',
    list_type TEXT DEFAULT 'dynamic' CHECK(list_type IN ('dynamic', 'static')),
    -- State
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- activity_feed (table)
CREATE TABLE activity_feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Actor
    collaborator_id INTEGER REFERENCES collaborators(id),
    -- Action
    action_type TEXT NOT NULL,
    -- 'task_created', 'task_updated', 'task_completed', 'task_assigned', 'comment_added', 'status_changed', etc.
    target_type TEXT NOT NULL,
    -- 'task', 'comment', 'shared_list', 'collaborator'
    target_id INTEGER NOT NULL,
    -- ID of the target entity
    
    -- Details
    description TEXT NOT NULL,
    metadata TEXT,
    -- JSON with extra context
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- audit_log (table)
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    -- create, update, delete, sync, login, export, etc.
  target_type TEXT,
    -- task, project, collaborator, system
  target_id INTEGER,
    details TEXT,
    -- JSON with changed fields
  ip_address TEXT,
    user_agent TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES collaborators(id)
);

-- api_credentials (table)
CREATE TABLE api_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL UNIQUE,
    -- leantime, todoist, jira, notion
  api_key_encrypted TEXT,
    -- encrypted API key/token
  api_secret_encrypted TEXT,
    -- encrypted API secret (if needed)
  extra_fields_encrypted TEXT,
    -- JSON encrypted extra fields
  last_used_at DATETIME,
    last_validated_at DATETIME,
    is_valid INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- backup_history (table)
CREATE TABLE backup_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_type TEXT NOT NULL,
    -- full, incremental, manual, auto
  file_path TEXT NOT NULL,
    file_size INTEGER,
    record_count INTEGER,
    checksum TEXT,
    -- SHA256 hash for integrity verification
  is_encrypted INTEGER DEFAULT 0,
    is_compressed INTEGER DEFAULT 1,
    status TEXT DEFAULT 'completed',
    -- pending, completed, failed, restored
  notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- security_events (table)
CREATE TABLE security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    -- failed_login, rate_limit, suspicious_activity, data_export, permission_change
  severity TEXT NOT NULL DEFAULT 'info',
    -- info, warning, critical
  source TEXT,
    -- ip address or system
  description TEXT,
    metadata TEXT,
    -- JSON with extra context
  resolved INTEGER DEFAULT 0,
    resolved_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- access_permissions (table)
CREATE TABLE access_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collaborator_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL,
    -- project, task, report, settings
  resource_id TEXT,
    -- specific resource ID or '*' for all
  permission TEXT NOT NULL,
    -- read, write, delete, admin
  granted_by INTEGER,
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collaborator_id) REFERENCES collaborators(id),
    FOREIGN KEY (granted_by) REFERENCES collaborators(id)
);

-- custom_fields (table)
CREATE TABLE custom_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    field_type TEXT NOT NULL,
    -- text, number, date, select, multiselect, checkbox, url
  options TEXT,
    -- JSON array of options for select/multiselect
  default_value TEXT,
    is_required INTEGER DEFAULT 0,
    show_in_list INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- user_preferences (table)
CREATE TABLE user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    pref_key TEXT NOT NULL UNIQUE,
    pref_value TEXT,
    pref_type TEXT DEFAULT 'string',
    -- string, number, boolean, json
  description TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES collaborators(id)
);

-- custom_views (table)
CREATE TABLE custom_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    owner_id INTEGER,
    filter_criteria TEXT,
    -- JSON filter config
  sort_criteria TEXT,
    -- JSON sort config
  display_columns TEXT,
    -- JSON array of columns to show
  group_by TEXT,
    is_default INTEGER DEFAULT 0,
    is_public INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES collaborators(id)
);

-- query_stats (table)
CREATE TABLE query_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_name TEXT NOT NULL,
    execution_time_ms REAL NOT NULL,
    rows_affected INTEGER DEFAULT 0,
    success INTEGER DEFAULT 1,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- cache_entries (table)
CREATE TABLE cache_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT UNIQUE NOT NULL,
    cache_value TEXT NOT NULL,
    cache_type TEXT DEFAULT 'json',
    ttl_seconds INTEGER DEFAULT 3600,
    hit_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    last_accessed_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT
);

-- batch_operations (table)
CREATE TABLE batch_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_type TEXT NOT NULL,
    description TEXT,
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    error_log TEXT
);

-- performance_snapshots (table)
CREATE TABLE performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_type TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- system_health_snapshots (table)
CREATE TABLE system_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    grade TEXT NOT NULL,
    issues INTEGER NOT NULL DEFAULT 0,
    checks INTEGER NOT NULL DEFAULT 0,
    healthy INTEGER NOT NULL,
    full_report TEXT NOT NULL,
    db_tables INTEGER,
    db_size_mb REAL,
    cron_total INTEGER,
    cron_success INTEGER,
    cron_failed INTEGER,
    revenue_received REAL,
    revenue_pending REAL,
    goals_active INTEGER,
    habits_logged_today INTEGER,
    tasks_total INTEGER,
    tasks_done INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- system_health_metrics (table)
CREATE TABLE system_health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_unit TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (snapshot_id) REFERENCES system_health_snapshots(id) ON DELETE CASCADE
);

-- data_pipeline_runs (table)
CREATE TABLE data_pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_name TEXT NOT NULL,
    source TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'partial', 'error')),
    records_read INTEGER DEFAULT 0,
    records_persisted INTEGER DEFAULT 0,
    records_routed INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    error_message TEXT,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- email_pipeline_events (table)
CREATE TABLE email_pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('success', 'skipped', 'error')),
    target_type TEXT,
    target_id TEXT,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email_id, action_type)
);

-- browser_bookmarks (table)
CREATE TABLE browser_bookmarks (
    bookmark_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'brave',
    profile_name TEXT NOT NULL,
    source_guid TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    folder_path TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    date_added TEXT,
    date_modified TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_run_id INTEGER REFERENCES data_pipeline_runs(id) ON DELETE SET NULL,
    lake_event_id TEXT,
    lake_run_id TEXT,
    lake_table TEXT,
    lake_raw_object_key TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(bookmark_id)) BETWEEN 1 AND 240),
    CHECK (length(trim(source)) BETWEEN 1 AND 64),
    CHECK (length(trim(profile_name)) BETWEEN 1 AND 160),
    CHECK (length(trim(title)) BETWEEN 1 AND 1000),
    CHECK (length(trim(url)) BETWEEN 1 AND 4096),
    CHECK (length(folder_path) <= 2000),
    CHECK (lake_raw_object_key IS NULL OR length(trim(lake_raw_object_key)) BETWEEN 1 AND 512)
);

-- universal_step_records (table)
CREATE TABLE universal_step_records (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL CHECK(length(trim(scope)) > 0),
    step_id TEXT NOT NULL CHECK(length(trim(step_id)) > 0),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('complete','current','upcoming','blocked','unverified','needs-review','operating','not-applicable')),
    owner TEXT,
    accountable_approver TEXT,
    reviewer TEXT,
    decision TEXT,
    outcome_json TEXT NOT NULL DEFAULT '{}',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    quality_json TEXT NOT NULL DEFAULT '{}',
    exception_or_waiver_json TEXT NOT NULL DEFAULT '{}',
    environment TEXT,
    method TEXT,
    integrity_ref TEXT,
    review_due_at TEXT,
    risks_json TEXT NOT NULL DEFAULT '[]',
    controls_json TEXT NOT NULL DEFAULT '[]',
    rollback_target TEXT,
    source_of_truth TEXT NOT NULL,
    privacy_class TEXT NOT NULL DEFAULT 'internal' CHECK(privacy_class IN ('public','internal','private','sensitive','restricted')),
    retention_class TEXT NOT NULL DEFAULT 'evidence' CHECK(retention_class IN ('operational','reference','evidence','financial','legal','personal','restricted','ephemeral','not-applicable')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scope, step_id, revision)
);

-- task_sync_ledger (table)
CREATE TABLE task_sync_ledger (
    task_id INTEGER PRIMARY KEY,
    source TEXT,
    sync_status TEXT NOT NULL CHECK(sync_status IN ('local','synced','dirty','conflict')),
    md_hash TEXT,
    last_synced_at TEXT,
    synced_version INTEGER
);

-- custom_field_values (table)
CREATE TABLE "custom_field_values" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (field_id) REFERENCES custom_fields(id) ON DELETE CASCADE,
    UNIQUE(task_id, field_id)
);

-- sync_queue (table)
CREATE TABLE "sync_queue" (
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

-- task_audit_log (table)
CREATE TABLE "task_audit_log" (
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

-- cell_cutovers (table)
CREATE TABLE cell_cutovers (
    cell TEXT PRIMARY KEY,
    rows INTEGER NOT NULL,
    verified_at TEXT NOT NULL
);

-- idx_sync_log_entity (index)
CREATE INDEX idx_sync_log_entity ON sync_log(entity_type, entity_id);

-- idx_repo_metrics_name (index)
CREATE INDEX idx_repo_metrics_name ON repo_metrics(repo_name);

-- idx_repo_metrics_date (index)
CREATE INDEX idx_repo_metrics_date ON repo_metrics(metric_date);

-- idx_calendar_events_start (index)
CREATE INDEX idx_calendar_events_start ON calendar_events(start_time);

-- idx_calendar_events_source (index)
CREATE INDEX idx_calendar_events_source ON calendar_events(source);

-- idx_emails_received (index)
CREATE INDEX idx_emails_received ON emails(received_at);

-- idx_emails_source (index)
CREATE INDEX idx_emails_source ON emails(source);

-- idx_external_tasks_due (index)
CREATE INDEX idx_external_tasks_due ON external_tasks(due_date);

-- idx_external_tasks_source (index)
CREATE INDEX idx_external_tasks_source ON external_tasks(source);

-- idx_external_tasks_status (index)
CREATE INDEX idx_external_tasks_status ON external_tasks(status);

-- idx_task_templates_active (index)
CREATE INDEX idx_task_templates_active ON task_templates(is_active);

-- idx_task_templates_usage (index)
CREATE INDEX idx_task_templates_usage ON task_templates(usage_count DESC);

-- idx_task_views_default (index)
CREATE INDEX idx_task_views_default ON task_views(is_default);

-- idx_notification_rules_active (index)
CREATE INDEX idx_notification_rules_active ON task_notification_rules(is_active);

-- idx_categories_parent (index)
CREATE INDEX idx_categories_parent ON categories(parent_id);

-- idx_categories_active (index)
CREATE INDEX idx_categories_active ON categories(is_active);

-- idx_snapshots_date (index)
CREATE INDEX idx_snapshots_date ON daily_snapshots(snapshot_date DESC);

-- idx_collab_active (index)
CREATE INDEX idx_collab_active ON collaborators(is_active);

-- idx_collab_email (index)
CREATE INDEX idx_collab_email ON collaborators(email);

-- idx_shared_owner (index)
CREATE INDEX idx_shared_owner ON shared_lists(owner_id);

-- idx_activity_target (index)
CREATE INDEX idx_activity_target ON activity_feed(target_type, target_id);

-- idx_activity_date (index)
CREATE INDEX idx_activity_date ON activity_feed(created_at DESC);

-- idx_activity_collab (index)
CREATE INDEX idx_activity_collab ON activity_feed(collaborator_id);

-- idx_query_stats_name (index)
CREATE INDEX idx_query_stats_name ON query_stats(query_name);

-- idx_query_stats_date (index)
CREATE INDEX idx_query_stats_date ON query_stats(created_at);

-- idx_cache_key (index)
CREATE INDEX idx_cache_key ON cache_entries(cache_key);

-- idx_cache_expires (index)
CREATE INDEX idx_cache_expires ON cache_entries(expires_at);

-- idx_batch_status (index)
CREATE INDEX idx_batch_status ON batch_operations(status);

-- idx_perf_snap_date (index)
CREATE INDEX idx_perf_snap_date ON performance_snapshots(created_at);

-- idx_perf_snap_type (index)
CREATE INDEX idx_perf_snap_type ON performance_snapshots(snapshot_type);

-- idx_system_health_snapshots_timestamp (index)
CREATE INDEX idx_system_health_snapshots_timestamp ON system_health_snapshots(timestamp DESC);

-- idx_system_health_snapshots_grade (index)
CREATE INDEX idx_system_health_snapshots_grade ON system_health_snapshots(grade);

-- idx_system_health_metrics_name_time (index)
CREATE INDEX idx_system_health_metrics_name_time ON system_health_metrics(metric_name, recorded_at DESC);

-- idx_pipeline_runs_source (index)
CREATE INDEX idx_pipeline_runs_source ON data_pipeline_runs(source, started_at DESC);

-- idx_pipeline_events_email (index)
CREATE INDEX idx_pipeline_events_email ON email_pipeline_events(email_id);

-- idx_pipeline_events_action (index)
CREATE INDEX idx_pipeline_events_action ON email_pipeline_events(action_type, status);

-- idx_emails_pipeline_status (index)
CREATE INDEX idx_emails_pipeline_status ON emails(pipeline_status, received_at DESC);

-- idx_emails_lake_event (index)
CREATE INDEX idx_emails_lake_event ON emails(lake_event_id);

-- idx_emails_lake_run (index)
CREATE INDEX idx_emails_lake_run ON emails(lake_run_id);

-- idx_browser_bookmarks_active (index)
CREATE INDEX idx_browser_bookmarks_active
    ON browser_bookmarks(source, is_active, profile_name);

-- idx_browser_bookmarks_url (index)
CREATE INDEX idx_browser_bookmarks_url
    ON browser_bookmarks(url);

-- idx_browser_bookmarks_folder (index)
CREATE INDEX idx_browser_bookmarks_folder
    ON browser_bookmarks(profile_name, folder_path);

-- idx_browser_bookmarks_lake_run (index)
CREATE INDEX idx_browser_bookmarks_lake_run
    ON browser_bookmarks(lake_run_id);

-- idx_audit_log_target_action_created (index)
CREATE INDEX idx_audit_log_target_action_created
  ON audit_log(target_type, action, created_at DESC);

-- idx_audit_log_created (index)
CREATE INDEX idx_audit_log_created
  ON audit_log(created_at DESC);

-- idx_task_audit_task (index)
CREATE INDEX idx_task_audit_task ON task_audit_log(task_id);

-- idx_task_audit_action (index)
CREATE INDEX idx_task_audit_action ON task_audit_log(action);

-- idx_task_audit_date (index)
CREATE INDEX idx_task_audit_date ON task_audit_log(created_at);
