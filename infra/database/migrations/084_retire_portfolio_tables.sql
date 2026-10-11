-- Retire the goals, projects/portfolio and roles/skills tables from the control plane
-- (owner direction 2026-10-10, one cell = one repo, backend and database). The rows
-- live in three cells made with solo-cell-kit, each with its own Neon database:
-- solo-goals, solo-projects and solo-roles-skills. Imported rows keep their old ids,
-- so ids kept in other tables stay valid. Every reader and writer goes through
-- infra/scripts/utils/cell_store.py (Python) or infra/mcp-server/src/cell-store.ts.
-- The old DDL lives on for tests in infra/tests/support/legacy_portfolio_tables.sql.
--
-- Guard: refuse to drop anything until the cutover recorded a verified import of
-- every cell (cellkit-import --verify: every old row is in the cell) in
-- cell_cutovers. The cutover writes those rows right before this migration runs.
-- Rebuilds run with foreign keys off (no cascade from a dropped parent, no check against a table being
-- replaced) and in one transaction, so a failure leaves nothing half-done.
PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE IF NOT EXISTS cell_cutovers (
    cell        TEXT PRIMARY KEY,
    rows        INTEGER NOT NULL,
    verified_at TEXT NOT NULL
);
CREATE TEMP TABLE retire_portfolio_guard (verified INTEGER NOT NULL CHECK (verified = 3));
INSERT INTO retire_portfolio_guard
    SELECT count(*) FROM cell_cutovers WHERE cell IN ('goals', 'projects', 'roles-skills');
DROP TABLE retire_portfolio_guard;

-- AUTOINCREMENT counters of the rebuilt tables, so ids are never handed out twice.
CREATE TEMP TABLE retire_portfolio_sequences AS
    SELECT name, seq FROM sqlite_sequence WHERE name IN ('progress_log', 'content_calendar', 'ai_conversation_logs',
                                                       'finance_subscriptions', 'operating_cycle_goal_links', 'crm_deals');

-- Tables that stay here lose their foreign keys into the retired tables (the ids stay as plain
-- integers that name rows in the cells). SQLite needs a rebuild to drop a foreign key; rows and
-- indexes are kept.
CREATE TABLE "progress_log__new" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id INTEGER,
    -- What was done
    activity_type TEXT CHECK(activity_type IN ('study', 'practice', 'project', 'teaching', 'review', 'other')),
    title TEXT NOT NULL,
    description TEXT,
    -- Metrics
    hours_spent REAL,
    progress_before INTEGER,
    progress_after INTEGER,
    -- Reflection
    what_learned TEXT,
    challenges TEXT,
    next_steps TEXT,
    -- Links
    evidence_url TEXT,
    -- link to proof (commit, article, etc.)

    logged_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO "progress_log__new" ("id", "skill_id", "activity_type", "title", "description", "hours_spent", "progress_before", "progress_after", "what_learned", "challenges", "next_steps", "evidence_url", "logged_at", "created_at") SELECT "id", "skill_id", "activity_type", "title", "description", "hours_spent", "progress_before", "progress_after", "what_learned", "challenges", "next_steps", "evidence_url", "logged_at", "created_at" FROM "progress_log";
DROP TABLE "progress_log";
ALTER TABLE "progress_log__new" RENAME TO "progress_log";
CREATE INDEX idx_progress_log_skill ON progress_log(skill_id);
CREATE INDEX idx_progress_log_date ON progress_log(logged_at);

CREATE TABLE "content_calendar__new" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    -- Content details
    content_type TEXT CHECK(content_type IN ('blog', 'newsletter', 'video', 'podcast', 'social', 'thread', 'carousel', 'course', 'template', 'other')) DEFAULT 'blog',
    topic TEXT,
    angle TEXT,
    -- the unique angle/hook
    target_audience TEXT,
    -- Platform & scheduling
    platform TEXT,
    -- twitter, linkedin, youtube, blog, newsletter, etc.
    scheduled_date DATE,
    published_at DATETIME,
    -- Status
    status TEXT CHECK(status IN ('idea', 'researching', 'outlining', 'drafting', 'review', 'scheduled', 'published', 'repurposed', 'killed')) DEFAULT 'idea',
    priority INTEGER DEFAULT 3,
    -- Content pipeline
    content_body TEXT,
    -- markdown draft
    word_count INTEGER DEFAULT 0,
    has_cta BOOLEAN DEFAULT 0,
    -- Distribution
    repurpose_from INTEGER REFERENCES content_calendar(id),
    repurpose_to TEXT,
    -- JSON array of platforms to repurpose to
    distribution_channels TEXT,
    -- JSON array

    -- Metrics
    views INTEGER DEFAULT 0,
    engagement INTEGER DEFAULT 0,
    leads_generated INTEGER DEFAULT 0,
    -- Relations
    related_project_id INTEGER,
    related_skill_ids TEXT,
    -- JSON array
    related_content_id INTEGER REFERENCES content(id),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO "content_calendar__new" ("id", "title", "content_type", "topic", "angle", "target_audience", "platform", "scheduled_date", "published_at", "status", "priority", "content_body", "word_count", "has_cta", "repurpose_from", "repurpose_to", "distribution_channels", "views", "engagement", "leads_generated", "related_project_id", "related_skill_ids", "related_content_id", "notes", "created_at", "updated_at") SELECT "id", "title", "content_type", "topic", "angle", "target_audience", "platform", "scheduled_date", "published_at", "status", "priority", "content_body", "word_count", "has_cta", "repurpose_from", "repurpose_to", "distribution_channels", "views", "engagement", "leads_generated", "related_project_id", "related_skill_ids", "related_content_id", "notes", "created_at", "updated_at" FROM "content_calendar";
DROP TABLE "content_calendar";
ALTER TABLE "content_calendar__new" RENAME TO "content_calendar";
CREATE INDEX idx_content_calendar_status ON content_calendar(status);
CREATE INDEX idx_content_calendar_date ON content_calendar(scheduled_date);
CREATE INDEX idx_content_calendar_platform ON content_calendar(platform);

CREATE TABLE "ai_conversation_logs__new" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Conversation content
    title TEXT NOT NULL,
    summary TEXT,
    prompt TEXT NOT NULL,
    response TEXT,
    ai_model TEXT,
    ai_provider TEXT,
    -- Categorization
    project_id INTEGER,
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
INSERT INTO "ai_conversation_logs__new" ("id", "title", "summary", "prompt", "response", "ai_model", "ai_provider", "project_id", "category", "tags", "tool_used", "session_id", "tokens_used", "duration_seconds", "outcome", "follow_up", "is_bookmarked", "logged_at", "created_at") SELECT "id", "title", "summary", "prompt", "response", "ai_model", "ai_provider", "project_id", "category", "tags", "tool_used", "session_id", "tokens_used", "duration_seconds", "outcome", "follow_up", "is_bookmarked", "logged_at", "created_at" FROM "ai_conversation_logs";
DROP TABLE "ai_conversation_logs";
ALTER TABLE "ai_conversation_logs__new" RENAME TO "ai_conversation_logs";
CREATE INDEX idx_ai_conversation_logs_project ON ai_conversation_logs(project_id);
CREATE INDEX idx_ai_conversation_logs_category ON ai_conversation_logs(category);
CREATE INDEX idx_ai_conversation_logs_date ON ai_conversation_logs(logged_at);
CREATE INDEX idx_ai_conversation_logs_bookmarked ON ai_conversation_logs(is_bookmarked);
CREATE INDEX idx_ai_conversation_logs_provider ON ai_conversation_logs(ai_provider);

CREATE TABLE "finance_subscriptions__new" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'software',
    owner_scope TEXT NOT NULL DEFAULT 'solo_empire'
        CHECK(owner_scope IN ('personal', 'solo_empire', 'venture', 'client', 'shared')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('trial', 'active', 'paused', 'cancelled', 'expired')),
    billing_interval TEXT NOT NULL DEFAULT 'monthly'
        CHECK(billing_interval IN ('weekly', 'monthly', 'quarterly', 'yearly', 'one_time', 'usage')),
    amount REAL NOT NULL CHECK(amount >= 0),
    currency TEXT NOT NULL DEFAULT 'THB',
    started_on DATE,
    next_billing_date DATE,
    cancelled_on DATE,
    auto_renew INTEGER NOT NULL DEFAULT 1 CHECK(auto_renew IN (0, 1)),
    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
    project_id INTEGER,
    goal_id INTEGER,
    source_ref TEXT,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, provider, owner_scope)
);
INSERT INTO "finance_subscriptions__new" ("id", "name", "provider", "category", "owner_scope", "status", "billing_interval", "amount", "currency", "started_on", "next_billing_date", "cancelled_on", "auto_renew", "account_id", "project_id", "goal_id", "source_ref", "notes", "created_at", "updated_at") SELECT "id", "name", "provider", "category", "owner_scope", "status", "billing_interval", "amount", "currency", "started_on", "next_billing_date", "cancelled_on", "auto_renew", "account_id", "project_id", "goal_id", "source_ref", "notes", "created_at", "updated_at" FROM "finance_subscriptions";
DROP TABLE "finance_subscriptions";
ALTER TABLE "finance_subscriptions__new" RENAME TO "finance_subscriptions";
CREATE INDEX idx_finance_subscriptions_status
    ON finance_subscriptions(owner_scope, status, next_billing_date);
CREATE INDEX idx_finance_subscriptions_account
    ON finance_subscriptions(account_id);
CREATE INDEX idx_finance_subscriptions_project
    ON finance_subscriptions(project_id);
CREATE INDEX idx_finance_subscriptions_goal
    ON finance_subscriptions(goal_id);

CREATE TABLE "operating_cycle_goal_links__new" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES "operating_cycles"(id) ON DELETE CASCADE,
    goal_id INTEGER NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'objective'
        CHECK(link_type IN ('objective', 'supporting', 'guardrail')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cycle_id, goal_id)
);
INSERT INTO "operating_cycle_goal_links__new" ("id", "cycle_id", "goal_id", "link_type", "created_at") SELECT "id", "cycle_id", "goal_id", "link_type", "created_at" FROM "operating_cycle_goal_links";
DROP TABLE "operating_cycle_goal_links";
ALTER TABLE "operating_cycle_goal_links__new" RENAME TO "operating_cycle_goal_links";
CREATE INDEX idx_operating_cycle_goal_links_goal
    ON operating_cycle_goal_links(goal_id, cycle_id);

CREATE TABLE "crm_deals__new" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    project_id INTEGER,
    stage TEXT CHECK(stage IN ('lead', 'contacted', 'discovery', 'proposal', 'negotiation', 'closed_won', 'closed_lost', 'churned')) DEFAULT 'lead',
    probability INTEGER DEFAULT 0 CHECK(probability >= 0 AND probability <= 100),
    deal_value REAL,
    currency TEXT DEFAULT 'THB',
    expected_close_date DATE,
    actual_close_date DATE,
    service_type TEXT,
    vertical TEXT,
    source TEXT,
    priority INTEGER DEFAULT 3,
    last_contact_date DATE,
    next_action TEXT,
    next_action_date DATE,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO "crm_deals__new" ("id", "title", "client_id", "project_id", "stage", "probability", "deal_value", "currency", "expected_close_date", "actual_close_date", "service_type", "vertical", "source", "priority", "last_contact_date", "next_action", "next_action_date", "notes", "created_at", "updated_at") SELECT "id", "title", "client_id", "project_id", "stage", "probability", "deal_value", "currency", "expected_close_date", "actual_close_date", "service_type", "vertical", "source", "priority", "last_contact_date", "next_action", "next_action_date", "notes", "created_at", "updated_at" FROM "crm_deals";
DROP TABLE "crm_deals";
ALTER TABLE "crm_deals__new" RENAME TO "crm_deals";
CREATE INDEX idx_crm_deals_stage ON crm_deals(stage);
CREATE INDEX idx_crm_deals_client ON crm_deals(client_id);
CREATE INDEX idx_crm_deals_project ON crm_deals(project_id);
CREATE INDEX idx_crm_deals_vertical ON crm_deals(vertical);
CREATE TRIGGER crm_agency_deal_revision
AFTER UPDATE ON crm_deals
WHEN NEW.vertical IN ('talent', 'real-estate')
BEGIN
    INSERT INTO crm_agency_deal_state (deal_id, revision) VALUES (NEW.id, 1)
    ON CONFLICT(deal_id) DO UPDATE SET revision = revision + 1;
END;

UPDATE sqlite_sequence SET seq = (SELECT k.seq FROM retire_portfolio_sequences k WHERE k.name = sqlite_sequence.name)
    WHERE name IN (SELECT name FROM retire_portfolio_sequences)
      AND seq < (SELECT k.seq FROM retire_portfolio_sequences k WHERE k.name = sqlite_sequence.name);
INSERT INTO sqlite_sequence (name, seq)
    SELECT name, seq FROM retire_portfolio_sequences WHERE name NOT IN (SELECT name FROM sqlite_sequence);
DROP TABLE retire_portfolio_sequences;

DROP VIEW IF EXISTS goal_attention_collision_summary;
DROP VIEW IF EXISTS goal_portfolio_current;

-- Children first (SQLite does not enforce the order, but it keeps the intent readable).
DROP TABLE IF EXISTS goal_task_project_links;
DROP TABLE IF EXISTS work_item_goal_task_links;
DROP TABLE IF EXISTS work_item_task_links;
DROP TABLE IF EXISTS goal_project_links;
DROP TABLE IF EXISTS goal_context_links;
DROP TABLE IF EXISTS goal_metrics;
DROP TABLE IF EXISTS goal_portfolio_mappings;
DROP TABLE IF EXISTS goal_tasks;
DROP TABLE IF EXISTS productivity_goals;
DROP TABLE IF EXISTS project_context_links;
DROP TABLE IF EXISTS project_repos;
DROP TABLE IF EXISTS portfolio_work_items;
DROP TABLE IF EXISTS personal_role_context_links;
DROP TABLE IF EXISTS personal_role_goal_links;
DROP TABLE IF EXISTS personal_role_project_links;
DROP TABLE IF EXISTS personal_role_task_links;
DROP TABLE IF EXISTS role_goal_links;
DROP TABLE IF EXISTS role_path_steps;
DROP TABLE IF EXISTS role_project_allocations;
DROP TABLE IF EXISTS role_skill_links;
DROP TABLE IF EXISTS skills;
DROP TABLE IF EXISTS skill_categories;
DROP TABLE IF EXISTS personal_roles;
DROP TABLE IF EXISTS portfolio_contexts;
DROP TABLE IF EXISTS goals;
DROP TABLE IF EXISTS projects;

COMMIT;
PRAGMA foreign_keys = ON;
