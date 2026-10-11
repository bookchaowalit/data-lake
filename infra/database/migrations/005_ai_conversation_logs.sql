-- Migration 005: Add AI conversation logs table
-- Stores AI interaction history, categorized by project

CREATE TABLE IF NOT EXISTS ai_conversation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Conversation content
    title TEXT NOT NULL,
    summary TEXT,
    prompt TEXT NOT NULL,
    response TEXT,
    ai_model TEXT,
    ai_provider TEXT,

    -- Categorization
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    category TEXT DEFAULT 'general',
    tags TEXT,

    -- Context
    tool_used TEXT,
    session_id TEXT,
    tokens_used INTEGER,
    duration_seconds REAL,

    -- Outcome
    outcome TEXT,
    follow_up TEXT,
    is_bookmarked BOOLEAN DEFAULT 0,

    logged_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ai_conversation_logs_project ON ai_conversation_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_ai_conversation_logs_category ON ai_conversation_logs(category);
CREATE INDEX IF NOT EXISTS idx_ai_conversation_logs_date ON ai_conversation_logs(logged_at);
CREATE INDEX IF NOT EXISTS idx_ai_conversation_logs_bookmarked ON ai_conversation_logs(is_bookmarked);
CREATE INDEX IF NOT EXISTS idx_ai_conversation_logs_provider ON ai_conversation_logs(ai_provider);
