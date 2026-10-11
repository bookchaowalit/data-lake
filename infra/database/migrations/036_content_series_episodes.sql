-- Migration 036: Local-first social content series episode tracking.
-- Tracks TikTok (and similar) multi-day series from idea through verified
-- publish and metrics review. Idempotent CREATE IF NOT EXISTS only.
-- No TikTok API, no automated posting, no fabricated URLs.

CREATE TABLE IF NOT EXISTS content_series_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_slug TEXT NOT NULL,
    day_number INTEGER NOT NULL CHECK (day_number >= 1),
    platform TEXT NOT NULL DEFAULT 'tiktok',
    account_handle TEXT NOT NULL,
    title TEXT,
    topic TEXT,
    script_path TEXT,
    planned_date DATE,
    status TEXT NOT NULL DEFAULT 'idea'
        CHECK (status IN (
            'idea',
            'drafting',
            'ready_to_record',
            'recorded',
            'edited',
            'approved',
            'published_user_confirmed',
            'published_verified',
            'metrics_reviewed'
        )),
    recorded_at DATETIME,
    published_at DATETIME,
    public_url TEXT,
    evidence_source TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (series_slug, day_number, platform),
    CHECK (length(trim(series_slug)) BETWEEN 1 AND 160),
    CHECK (length(trim(platform)) BETWEEN 1 AND 64),
    CHECK (length(trim(account_handle)) BETWEEN 1 AND 120),
    CHECK (public_url IS NULL OR length(trim(public_url)) BETWEEN 8 AND 2048),
    CHECK (
        status NOT IN ('published_verified', 'metrics_reviewed')
        OR (public_url IS NOT NULL AND length(trim(public_url)) >= 8)
    )
);

CREATE INDEX IF NOT EXISTS idx_content_series_episodes_status
    ON content_series_episodes(series_slug, status, day_number);

CREATE INDEX IF NOT EXISTS idx_content_series_episodes_platform
    ON content_series_episodes(platform, account_handle, status);

CREATE INDEX IF NOT EXISTS idx_content_series_episodes_planned
    ON content_series_episodes(planned_date, status);

CREATE TABLE IF NOT EXISTS content_series_episode_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL
        REFERENCES content_series_episodes(id) ON DELETE CASCADE,
    views INTEGER CHECK (views IS NULL OR views >= 0),
    likes INTEGER CHECK (likes IS NULL OR likes >= 0),
    comments INTEGER CHECK (comments IS NULL OR comments >= 0),
    shares INTEGER CHECK (shares IS NULL OR shares >= 0),
    saves INTEGER CHECK (saves IS NULL OR saves >= 0),
    profile_views INTEGER CHECK (profile_views IS NULL OR profile_views >= 0),
    followers INTEGER CHECK (followers IS NULL OR followers >= 0),
    captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (episode_id, captured_at, source),
    CHECK (length(trim(source)) BETWEEN 1 AND 64)
);

CREATE INDEX IF NOT EXISTS idx_content_series_metrics_episode
    ON content_series_episode_metrics(episode_id, captured_at DESC);
