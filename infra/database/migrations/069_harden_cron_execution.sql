-- Migration 069: harden cron execution and spread active work across the day.
-- Retry state makes cron_heal a single automatic retry per failed scheduled
-- run. A later primary run resets the counter through cron_runner.

ALTER TABLE cron_jobs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cron_jobs ADD COLUMN last_retry_at DATETIME;

-- Avoid running the same goal-progress script twice every day. Keep the row
-- for history and manual inspection, inactive rows are never installed.
UPDATE cron_jobs
SET is_active = 0,
    last_status = 'disabled'
WHERE job_type = 'goal_progress'
  AND is_active = 1;

-- Spread the active daily batch so SQLite writes and downstream reports do
-- not all contend at 00:00. Raw five-field expressions are used so the live
-- crontab and health monitor share an unambiguous schedule contract.
UPDATE cron_jobs SET schedule = '5 0 * * *' WHERE job_type = 'take_snapshot' AND is_active = 1;
UPDATE cron_jobs SET schedule = '15 0 * * *' WHERE job_type = 'generate_tasks' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 0 * * *' WHERE job_type = 'check_notifications' AND is_active = 1;
UPDATE cron_jobs SET schedule = '45 0 * * *' WHERE job_type = 'update_goals' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 1 * * *' WHERE job_type = 'revenue_autorun' AND is_active = 1;
UPDATE cron_jobs SET schedule = '15 1 * * *' WHERE job_type = 'db_health_check' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 1 * * *' WHERE job_type = 'system_status' AND is_active = 1;
UPDATE cron_jobs SET schedule = '45 1 * * *' WHERE job_type = 'analytics_dashboard' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 2 * * *' WHERE job_type = 'revenue_analytics' AND is_active = 1;
UPDATE cron_jobs SET schedule = '15 2 * * *' WHERE job_type = 'habit_analytics' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 2 * * *' WHERE job_type = 'goal_velocity' AND is_active = 1;
UPDATE cron_jobs SET schedule = '45 2 * * *' WHERE job_type = 'time_analytics' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 3 * * *' WHERE job_type = 'backup_db' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 4 * * *' WHERE job_type = 'engagement_notifications' AND is_active = 1;
UPDATE cron_jobs SET schedule = '15 4 * * *' WHERE job_type = 'decision_review' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 4 * * *' WHERE job_type = 'decision_brief_daily' AND is_active = 1;
UPDATE cron_jobs SET schedule = '45 4 * * *' WHERE job_type = 'daily_diary' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 5 * * *' WHERE job_type = 'book_dev_loop' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 6 * * *' WHERE job_type = 'smart_sync' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 0 * * 0' WHERE job_type = 'auto_archive' AND is_active = 1;
UPDATE cron_jobs SET schedule = '15 0 * * 0' WHERE job_type = 'weekly_habit_autogranted' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 0 * * 0' WHERE job_type = 'weekly_review_gen' AND is_active = 1;
UPDATE cron_jobs SET schedule = '45 0 * * 0' WHERE job_type = 'domain_scanner' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 1 * * 0' WHERE job_type = 'media_lifecycle' AND is_active = 1;
UPDATE cron_jobs SET schedule = '15 1 * * 0' WHERE job_type = 'decision_brief_weekly' AND is_active = 1;
UPDATE cron_jobs SET schedule = '30 1 * * 0' WHERE job_type = 'diary_weekly_summary' AND is_active = 1;
UPDATE cron_jobs SET schedule = '45 1 * * 0' WHERE job_type = 'sales_pipeline' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 2 1 * *' WHERE job_type = 'diary_monthly_summary' AND is_active = 1;
