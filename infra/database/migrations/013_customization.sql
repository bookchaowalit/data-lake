-- Migration 013: Customization
-- Custom fields, user preferences, custom task types, workflows

-- Custom field definitions
CREATE TABLE IF NOT EXISTS custom_fields (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  field_type TEXT NOT NULL,        -- text, number, date, select, multiselect, checkbox, url
  options TEXT,                    -- JSON array of options for select/multiselect
  default_value TEXT,
  is_required INTEGER DEFAULT 0,
  show_in_list INTEGER DEFAULT 0,
  sort_order INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Custom field values for tasks
CREATE TABLE IF NOT EXISTS custom_field_values (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  field_id INTEGER NOT NULL,
  value TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
  FOREIGN KEY (field_id) REFERENCES custom_fields(id) ON DELETE CASCADE,
  UNIQUE(task_id, field_id)
);

-- User preferences/settings
CREATE TABLE IF NOT EXISTS user_preferences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  pref_key TEXT NOT NULL UNIQUE,
  pref_value TEXT,
  pref_type TEXT DEFAULT 'string',  -- string, number, boolean, json
  description TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES collaborators(id)
);

-- Custom task types/workflows
CREATE TABLE IF NOT EXISTS task_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  icon TEXT,                       -- emoji or icon name
  color TEXT,                      -- hex color
  default_status TEXT DEFAULT 'todo',
  allowed_statuses TEXT,           -- JSON array of statuses for this type
  custom_template TEXT,            -- JSON template for default values
  is_active INTEGER DEFAULT 1,
  sort_order INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Custom views/saved filters
CREATE TABLE IF NOT EXISTS custom_views (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  owner_id INTEGER,
  filter_criteria TEXT,            -- JSON filter config
  sort_criteria TEXT,              -- JSON sort config
  display_columns TEXT,            -- JSON array of columns to show
  group_by TEXT,
  is_default INTEGER DEFAULT 0,
  is_public INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (owner_id) REFERENCES collaborators(id)
);

-- Seed default preferences
INSERT OR IGNORE INTO user_preferences (pref_key, pref_value, pref_type, description) VALUES
  ('theme', 'system', 'string', 'UI theme: light, dark, system'),
  ('timezone', 'Asia/Bangkok', 'string', 'Default timezone'),
  ('date_format', 'YYYY-MM-DD', 'string', 'Date display format'),
  ('default_view', 'list', 'string', 'Default task view: list, board, calendar'),
  ('notifications_enabled', 'true', 'boolean', 'Enable desktop notifications'),
  ('sync_interval', '30', 'number', 'Auto-sync interval in minutes'),
  ('week_start', 'monday', 'string', 'First day of week: monday, sunday');

-- Seed default task types
INSERT OR IGNORE INTO task_types (name, description, icon, color, default_status, allowed_statuses, sort_order) VALUES
  ('Standard', 'Regular task', '📝', '#3b82f6', 'todo', '["todo","in_progress","done","cancelled"]', 1),
  ('Bug', 'Bug fix or issue', '🐛', '#ef4444', 'todo', '["todo","in_progress","testing","done"]', 2),
  ('Feature', 'New feature development', '✨', '#10b981', 'todo', '["todo","in_progress","review","done"]', 3),
  ('Meeting', 'Meeting or call', '📅', '#8b5cf6', 'todo', '["todo","scheduled","completed","cancelled"]', 4),
  ('Idea', 'Idea or brainstorm', '💡', '#f59e0b', 'todo', '["todo","exploring","validated","rejected"]', 5);
