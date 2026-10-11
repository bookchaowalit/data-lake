-- Migration 015: Notification tracking for the Go notifier service
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    channel TEXT NOT NULL,          -- console, line, slack, email
    message TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_notif_task ON notifications(task_id);
CREATE INDEX IF NOT EXISTS idx_notif_sent ON notifications(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_unread ON notifications(is_read) WHERE is_read = 0;
