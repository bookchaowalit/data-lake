-- Brave bookmark source and local operational projection.
--
-- The exact Brave JSON remains in the lake landing layer. This table contains
-- only the searchable, mutable projection and lake lineage pointers.

CREATE TABLE IF NOT EXISTS browser_bookmarks (
    bookmark_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'brave',
    profile_name TEXT NOT NULL,
    source_guid TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    folder_path TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    date_added TEXT,
    date_modified TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_run_id INTEGER REFERENCES data_pipeline_runs(id) ON DELETE SET NULL,
    lake_event_id TEXT,
    lake_run_id TEXT,
    lake_table TEXT,
    lake_raw_object_key TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CHECK (length(trim(bookmark_id)) BETWEEN 1 AND 240),
    CHECK (length(trim(source)) BETWEEN 1 AND 64),
    CHECK (length(trim(profile_name)) BETWEEN 1 AND 160),
    CHECK (length(trim(title)) BETWEEN 1 AND 1000),
    CHECK (length(trim(url)) BETWEEN 1 AND 4096),
    CHECK (length(folder_path) <= 2000),
    CHECK (lake_raw_object_key IS NULL OR length(trim(lake_raw_object_key)) BETWEEN 1 AND 512)
);

CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_active
    ON browser_bookmarks(source, is_active, profile_name);

CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_url
    ON browser_bookmarks(url);

CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_folder
    ON browser_bookmarks(profile_name, folder_path);

CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_lake_run
    ON browser_bookmarks(lake_run_id);

INSERT INTO source_registry (
    source_key, display_name, source_kind, provider, domain, dataset,
    owner_scope, privacy_class, retention_class, ingest_mode, status, description
)
SELECT
    'brave-bookmarks', 'Brave Browser Bookmarks', 'file', 'Brave',
    'knowledge', 'browser_bookmarks', 'personal', 'private', 'operational',
    'batch', 'active',
    'Local Brave bookmark JSON imported into the Solo Empire lake and search projection'
WHERE NOT EXISTS (
    SELECT 1 FROM source_registry WHERE source_key = 'brave-bookmarks'
);
