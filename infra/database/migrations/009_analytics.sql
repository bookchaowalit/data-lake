-- Migration 009: Analytics & Time Tracking
-- Adds: time tracking, daily snapshots, productivity metrics

-- =====================================================
-- TIME TRACKING: Track time spent on tasks
-- =====================================================
CREATE TABLE IF NOT EXISTS time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    
    -- Time data
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    duration_seconds INTEGER,  -- Calculated on stop
    
    -- Source
    source TEXT DEFAULT 'manual',  -- manual, pomodoro, auto
    notes TEXT,
    
    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id);
CREATE INDEX IF NOT EXISTS idx_time_started ON time_entries(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_time_active ON time_entries(ended_at) WHERE ended_at IS NULL;

-- =====================================================
-- DAILY SNAPSHOTS: Track daily task state for trends
-- =====================================================
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL UNIQUE,
    
    -- Task counts
    total_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    active_tasks INTEGER DEFAULT 0,
    overdue_tasks INTEGER DEFAULT 0,
    blocked_tasks INTEGER DEFAULT 0,
    
    -- Completions this day
    completed_today INTEGER DEFAULT 0,
    created_today INTEGER DEFAULT 0,
    
    -- Time tracking
    total_time_seconds INTEGER DEFAULT 0,
    
    -- By project (JSON)
    project_breakdown TEXT,  -- {"Project A": 5, "Project B": 3}
    
    -- By priority (JSON)
    priority_breakdown TEXT,  -- {"1": 2, "2": 5, "3": 10}
    
    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date DESC);

-- =====================================================
-- PRODUCTIVITY GOALS: Set and track productivity targets
-- =====================================================
CREATE TABLE IF NOT EXISTS productivity_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    goal_type TEXT NOT NULL CHECK(goal_type IN (
        'daily_completions',    -- Complete N tasks per day
        'weekly_completions',   -- Complete N tasks per week
        'daily_time',           -- Track N hours per day
        'weekly_time',          -- Track N hours per week
        'streak'                -- Maintain N day completion streak
    )),
    
    target_value REAL NOT NULL,
    current_value REAL DEFAULT 0,
    
    -- Period
    period_start DATE,
    period_end DATE,
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goals_active ON productivity_goals(is_active);
CREATE INDEX IF NOT EXISTS idx_goals_type ON productivity_goals(goal_type);

-- =====================================================
-- SEED DEFAULT PRODUCTIVITY GOALS
-- =====================================================
INSERT OR IGNORE INTO productivity_goals (name, goal_type, target_value, period_start, period_end)
VALUES 
    ('Daily Tasks', 'daily_completions', 5.0, DATE('now'), DATE('now', '+1 day')),
    ('Weekly Tasks', 'weekly_completions', 25.0, DATE('now', 'weekday 1', '-7 days'), DATE('now', 'weekday 1')),
    ('Daily Focus Time', 'daily_time', 14400.0, DATE('now'), DATE('now', '+1 day'));  -- 4 hours in seconds
