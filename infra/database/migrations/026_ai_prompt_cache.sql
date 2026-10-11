CREATE TABLE IF NOT EXISTS ai_prompt_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    route TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    cache_value TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'json',
    token_count INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    privacy_class TEXT NOT NULL DEFAULT 'internal' CHECK (privacy_class IN ('public', 'internal')),
    ttl_seconds INTEGER NOT NULL DEFAULT 3600 CHECK (ttl_seconds > 0),
    hit_count INTEGER NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_prompt_cache_route_model ON ai_prompt_cache(route, model);
CREATE INDEX IF NOT EXISTS idx_ai_prompt_cache_expires ON ai_prompt_cache(expires_at);
