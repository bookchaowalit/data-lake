CREATE TABLE IF NOT EXISTS system_health_snapshots (
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

CREATE TABLE IF NOT EXISTS system_health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_unit TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (snapshot_id) REFERENCES system_health_snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_system_health_snapshots_timestamp ON system_health_snapshots(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_system_health_snapshots_grade ON system_health_snapshots(grade);

CREATE INDEX IF NOT EXISTS idx_system_health_metrics_name_time ON system_health_metrics(metric_name, recorded_at DESC);
