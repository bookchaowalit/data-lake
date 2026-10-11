-- Migration 011: Collaboration System
-- Adds: collaborators, shared lists, activity feed
-- Note: task_comments and task_assignments already exist from Phase 1

-- =====================================================
-- COLLABORATORS: Team members / shared users
-- =====================================================
CREATE TABLE IF NOT EXISTS collaborators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    role TEXT DEFAULT 'member' CHECK(role IN ('owner', 'admin', 'member', 'viewer')),
    avatar_url TEXT,
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_collab_active ON collaborators(is_active);
CREATE INDEX IF NOT EXISTS idx_collab_email ON collaborators(email);

-- =====================================================
-- SHARED LISTS: Curated task collections for teams
-- =====================================================
CREATE TABLE IF NOT EXISTS shared_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    owner_id INTEGER REFERENCES collaborators(id),
    
    -- Access
    visibility TEXT DEFAULT 'private' CHECK(visibility IN ('private', 'team', 'public')),
    
    -- Filter criteria (JSON) — dynamic lists
    -- e.g. {"project": "DCS", "status": ["todo", "in_progress"], "priority": [1, 2]}
    filter_criteria TEXT,
    
    -- Manual task list (JSON array of task IDs) — for static lists
    task_ids TEXT DEFAULT '[]',
    
    list_type TEXT DEFAULT 'dynamic' CHECK(list_type IN ('dynamic', 'static')),
    
    -- State
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shared_owner ON shared_lists(owner_id);

-- =====================================================
-- ACTIVITY FEED: Track all changes
-- =====================================================
CREATE TABLE IF NOT EXISTS activity_feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Actor
    collaborator_id INTEGER REFERENCES collaborators(id),
    
    -- Action
    action_type TEXT NOT NULL,  -- 'task_created', 'task_updated', 'task_completed', 'task_assigned', 'comment_added', 'status_changed', etc.
    target_type TEXT NOT NULL,  -- 'task', 'comment', 'shared_list', 'collaborator'
    target_id INTEGER NOT NULL, -- ID of the target entity
    
    -- Details
    description TEXT NOT NULL,
    metadata TEXT,  -- JSON with extra context
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activity_target ON activity_feed(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_activity_date ON activity_feed(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_collab ON activity_feed(collaborator_id);

-- =====================================================
-- SEED DEFAULT COLLABORATOR (the owner)
-- =====================================================
INSERT OR IGNORE INTO collaborators (name, email, role)
VALUES ('Owner', 'owner@local', 'owner');
