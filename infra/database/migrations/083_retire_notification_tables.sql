-- Retire the notification tables from the control plane (owner direction 2026-10-10,
-- one cell = one repo, backend and database). Rules and the notification log
-- live in the solo-notifications cell (its own Neon database), and every reader
-- and writer goes through infra/scripts/utils/notifications_store.py or the Go
-- notifier's client. The six rules were imported into the cell first (keeping
-- their ids as legacy_id, parity checked). The log and the unused legacy
-- notifications table held no rows. The old DDL lives on for tests in
-- infra/tests/support/legacy_notification_tables.sql.
-- Guard: refuse to drop log data (the rules are copied, the log never was).
CREATE TEMP TABLE retire_notifications_guard (rows_left INTEGER NOT NULL CHECK (rows_left = 0));
INSERT INTO retire_notifications_guard SELECT (SELECT count(*) FROM notification_log)
    + (SELECT count(*) FROM notifications);
DROP TABLE retire_notifications_guard;
DROP TABLE IF EXISTS notification_log;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS notification_rules;
