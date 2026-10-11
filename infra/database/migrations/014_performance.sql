-- Migration 014: Performance optimization tables
-- Provides: query_stats, cache_entries, batch_operations, performance_snapshots

-- Query statistics tracking
CREATE TABLE IF NOT EXISTS query_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_name TEXT NOT NULL,
    execution_time_ms REAL NOT NULL,
    rows_affected INTEGER DEFAULT 0,
    success INTEGER DEFAULT 1,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Cache entries for frequently accessed data
CREATE TABLE IF NOT EXISTS cache_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT UNIQUE NOT NULL,
    cache_value TEXT NOT NULL,
    cache_type TEXT DEFAULT 'json',
    ttl_seconds INTEGER DEFAULT 3600,
    hit_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    last_accessed_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT
);

-- Batch operation tracking
CREATE TABLE IF NOT EXISTS batch_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_type TEXT NOT NULL,
    description TEXT,
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    error_log TEXT
);

-- Performance snapshots (periodic DB health checks)
CREATE TABLE IF NOT EXISTS performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_type TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for performance tables
CREATE INDEX IF NOT EXISTS idx_query_stats_name ON query_stats(query_name);
CREATE INDEX IF NOT EXISTS idx_query_stats_date ON query_stats(created_at);
CREATE INDEX IF NOT EXISTS idx_cache_key ON cache_entries(cache_key);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_batch_status ON batch_operations(status);
CREATE INDEX IF NOT EXISTS idx_perf_snap_date ON performance_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_perf_snap_type ON performance_snapshots(snapshot_type);
