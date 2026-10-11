-- Migration 070: normalize remaining cadence aliases to explicit cron fields.
-- This keeps the database row, installed crontab, and health monitor output
-- directly comparable without interpreting an alias in three places.

UPDATE cron_jobs SET schedule = '0 */4 * * *' WHERE job_type = 'cron_heal' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 */4 * * *' WHERE job_type = 'brave_bookmarks_maintenance' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 */6 * * *' WHERE job_type = 'data_freshness' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 6 * * *' WHERE job_type = 'sync_gmail' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 8,20 * * *' WHERE job_type = 'run_alerts' AND is_active = 1;
UPDATE cron_jobs SET schedule = '0 8,20 * * *' WHERE job_type = 'refresh_dashboards' AND is_active = 1;
