-- Register the private, local-only daily activity diary generator.
-- The job reads metadata from SQLite and root git history, then writes only
-- diary/entries/YYYY/MM/DD/auto-daily.md. It never sends messages or calls AI.

CREATE TABLE cron_jobs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    schedule TEXT NOT NULL,
    job_type TEXT NOT NULL CHECK(job_type IN (
        'sync', 'smart_sync', 'generate_tasks', 'check_reminders',
        'check_notifications', 'engagement_notifications', 'take_snapshot',
        'auto_archive', 'run_pipeline', 'update_goals', 'revenue_autorun',
        'weekly_habit_autogranted', 'weekly_review_gen', 'goal_progress',
        'db_health_check', 'system_status', 'domain_scanner', 'run_alerts',
        'sync_calendar', 'sync_gmail', 'sync_leantime', 'sync_strava',
        'sync_binance', 'sync_all', 'refresh_dashboards', 'backup_db',
        'analytics_dashboard', 'revenue_analytics', 'habit_analytics',
        'goal_velocity', 'time_analytics', 'cron_heal', 'data_freshness',
        'gmail_categorize', 'gmail_to_todoist', 'gmail_daily_digest',
        'gmail_filters', 'reconcile_overdue', 'insights', 'generate_pages',
        'publish_pages', 'media_lifecycle', 'decision_review',
        'decision_brief_daily', 'decision_brief_weekly', 'daily_diary'
    )),
    params TEXT DEFAULT '{}',
    is_active BOOLEAN DEFAULT 1,
    last_run_at DATETIME,
    next_run_at DATETIME,
    last_status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO cron_jobs_new (
    id, name, description, schedule, job_type, params, is_active,
    last_run_at, next_run_at, last_status, created_at
)
SELECT
    id, name, description, schedule, job_type, params, is_active,
    last_run_at, next_run_at, last_status, created_at
FROM cron_jobs;

DROP TABLE cron_jobs;
ALTER TABLE cron_jobs_new RENAME TO cron_jobs;
CREATE INDEX IF NOT EXISTS idx_cron_active ON cron_jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_cron_next ON cron_jobs(next_run_at);

INSERT INTO cron_jobs (
    name, description, schedule, job_type, params, is_active
)
SELECT
    'Daily Activity Diary',
    'Write a private date-partitioned activity roll-up without raw prompts or journal text',
    'daily',
    'daily_diary',
    '{}',
    1
WHERE NOT EXISTS (
    SELECT 1 FROM cron_jobs WHERE job_type = 'daily_diary'
);
