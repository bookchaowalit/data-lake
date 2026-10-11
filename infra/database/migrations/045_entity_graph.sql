-- 045_entity_graph.sql
-- Add a central, FK-backed traceability graph without replacing domain tables.

CREATE TABLE IF NOT EXISTS entity_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    canonical_path TEXT,
    title TEXT NOT NULL,
    owner_scope TEXT,
    metadata TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_type, entity_key),
    UNIQUE(source_table, source_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_registry_type ON entity_registry(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_registry_source ON entity_registry(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_entity_registry_active ON entity_registry(is_active);

CREATE TABLE IF NOT EXISTS entity_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL REFERENCES entity_registry(id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES entity_registry(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'entity-graph',
    metadata TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(source_entity_id <> target_entity_id),
    UNIQUE(source_entity_id, target_entity_id, relation_type, source)
);

CREATE INDEX IF NOT EXISTS idx_entity_links_source ON entity_links(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_target ON entity_links(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_relation ON entity_links(relation_type);
