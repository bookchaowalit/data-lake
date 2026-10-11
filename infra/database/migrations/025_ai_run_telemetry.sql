CREATE TABLE IF NOT EXISTS ai_run_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    route TEXT NOT NULL,
    prompt_version TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
    token_budget INTEGER CHECK (token_budget IS NULL OR token_budget >= 0),
    latency_ms REAL CHECK (latency_ms IS NULL OR latency_ms >= 0),
    estimated_cost_usd REAL CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
    cache_hit BOOLEAN NOT NULL DEFAULT 0 CHECK (cache_hit IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'success',
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ai_run_telemetry_route ON ai_run_telemetry(route);
CREATE INDEX IF NOT EXISTS idx_ai_run_telemetry_model ON ai_run_telemetry(provider, model);
CREATE INDEX IF NOT EXISTS idx_ai_run_telemetry_created ON ai_run_telemetry(created_at);
