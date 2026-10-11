ALTER TABLE notification_log ADD COLUMN delivered_at DATETIME;
ALTER TABLE notification_log ADD COLUMN delivery_channel TEXT;
ALTER TABLE notification_log ADD COLUMN delivery_error TEXT;
ALTER TABLE notification_log ADD COLUMN delivery_attempts INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_notification_log_delivery
    ON notification_log (notification_type, delivered_at, id);

INSERT OR IGNORE INTO cron_jobs (
    name, description, schedule, job_type, params, is_active
)
VALUES (
    'Engagement Notification Queue',
    'Queue deduplicated engagement review digests for the notifier service',
    'daily',
    'engagement_notifications',
    '{"days": 3}',
    1
);
