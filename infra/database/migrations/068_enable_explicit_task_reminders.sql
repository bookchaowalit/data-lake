-- Migration 068: Enable explicit task reminders.
-- A reminder_at value is opt-in. This rule does not create reminders for
-- existing tasks and does not claim that console logging reached a device.

INSERT INTO notification_rules
    (name, description, rule_type, config, channels, check_interval_minutes, is_active)
SELECT
    'Explicit Task Reminders',
    'Notify when an opted-in task reminder_at has been reached',
    'reminder',
    '{}',
    '["console"]',
    15,
    1
WHERE NOT EXISTS (
    SELECT 1 FROM notification_rules WHERE rule_type = 'reminder'
);
