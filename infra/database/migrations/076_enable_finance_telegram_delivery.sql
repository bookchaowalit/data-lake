-- Clarify that the Finance daily queue is delivered by the configured
-- Telegram channel after the local notification record is committed.

UPDATE cron_jobs
SET description = 'Queue aggregate Finance attention signals and deliver them through the configured Telegram bot'
WHERE job_type = 'finance_daily_notification';
