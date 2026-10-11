-- Migration 065: Goal portfolio and attention mapping
-- Add a reversible planning layer without changing or merging existing goals.

CREATE TABLE IF NOT EXISTS goal_portfolio_mappings (
    goal_id INTEGER PRIMARY KEY REFERENCES goals(id) ON DELETE CASCADE,
    portfolio_bucket TEXT NOT NULL CHECK (portfolio_bucket IN (
        'active_bet',
        'infrastructure',
        'maintenance',
        'capability_backlog',
        'option_portfolio',
        'large_scale_builder',
        'frontier',
        'someday_curiosity'
    )),
    attention_class TEXT NOT NULL CHECK (attention_class IN (
        'focus',
        'parallel',
        'background',
        'maintenance',
        'explore',
        'option'
    )),
    attention_cost INTEGER NOT NULL DEFAULT 0 CHECK (attention_cost >= 0 AND attention_cost <= 5),
    collision_group TEXT NOT NULL,
    canonical_goal TEXT NOT NULL,
    canonical_goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    current_season TEXT NOT NULL,
    mapping_confidence TEXT NOT NULL DEFAULT 'provisional' CHECK (mapping_confidence IN (
        'high',
        'provisional',
        'review'
    )),
    mapping_source TEXT NOT NULL DEFAULT 'goal-portfolio-rule-v1',
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goal_portfolio_bucket
    ON goal_portfolio_mappings(portfolio_bucket, current_season);

CREATE INDEX IF NOT EXISTS idx_goal_portfolio_attention
    ON goal_portfolio_mappings(attention_class, attention_cost, current_season);

CREATE INDEX IF NOT EXISTS idx_goal_portfolio_collision
    ON goal_portfolio_mappings(collision_group, current_season);

CREATE INDEX IF NOT EXISTS idx_goal_portfolio_canonical
    ON goal_portfolio_mappings(canonical_goal, current_season);

CREATE VIEW IF NOT EXISTS goal_portfolio_current AS
SELECT
    g.id AS goal_id,
    g.title,
    g.description,
    g.type,
    g.category,
    g.status,
    g.priority,
    g.progress_percent,
    g.due_date,
    m.portfolio_bucket,
    m.attention_class,
    m.attention_cost,
    m.collision_group,
    m.canonical_goal,
    m.canonical_goal_id,
    m.current_season,
    m.mapping_confidence,
    m.mapping_source,
    m.notes AS mapping_notes,
    m.updated_at AS mapping_updated_at
FROM goals g
JOIN goal_portfolio_mappings m ON m.goal_id = g.id;

CREATE VIEW IF NOT EXISTS goal_attention_collision_summary AS
WITH canonical_families AS (
    SELECT
        m.current_season,
        m.attention_class,
        m.attention_cost,
        m.collision_group,
        m.canonical_goal
    FROM goal_portfolio_mappings m
    JOIN goals g ON g.id = m.goal_id
    WHERE g.status IN ('active', 'planning')
    GROUP BY
        m.current_season,
        m.attention_class,
        m.attention_cost,
        m.collision_group,
        m.canonical_goal
)
SELECT
    current_season,
    attention_class,
    collision_group,
    COUNT(*) AS canonical_goal_count,
    SUM(attention_cost) AS attention_cost
FROM canonical_families
GROUP BY current_season, attention_class, collision_group;
