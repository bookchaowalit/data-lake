CREATE TABLE IF NOT EXISTS business_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    grade TEXT NOT NULL,
    issues INTEGER NOT NULL DEFAULT 0,
    checks INTEGER NOT NULL DEFAULT 0,
    healthy INTEGER NOT NULL,
    full_report TEXT NOT NULL,
    revenue_total REAL,
    revenue_received REAL,
    revenue_pending REAL,
    outreach_count INTEGER,
    outreach_pending INTEGER,
    follow_ups_overdue INTEGER,
    content_drafts INTEGER,
    content_published INTEGER,
    tasks_total INTEGER,
    tasks_done INTEGER,
    tasks_in_progress INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS business_kpis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER,
    kpi_name TEXT NOT NULL,
    kpi_value REAL NOT NULL,
    kpi_target REAL,
    kpi_unit TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (snapshot_id) REFERENCES business_health_snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_business_health_snapshots_timestamp ON business_health_snapshots(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_business_health_snapshots_grade ON business_health_snapshots(grade);

CREATE INDEX IF NOT EXISTS idx_business_kpis_name_time ON business_kpis(kpi_name, recorded_at DESC);
