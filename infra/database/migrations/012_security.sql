-- Migration 012: Security
-- Audit logging, encrypted credentials, backup tracking, security events

-- Comprehensive audit log for all task operations
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,           -- create, update, delete, sync, login, export, etc.
  target_type TEXT,               -- task, project, collaborator, system
  target_id INTEGER,
  details TEXT,                   -- JSON with changed fields
  ip_address TEXT,
  user_agent TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES collaborators(id)
);

-- Encrypted API credential storage
CREATE TABLE IF NOT EXISTS api_credentials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL UNIQUE,    -- leantime, todoist, jira, notion
  api_key_encrypted TEXT,         -- encrypted API key/token
  api_secret_encrypted TEXT,      -- encrypted API secret (if needed)
  extra_fields_encrypted TEXT,    -- JSON encrypted extra fields
  last_used_at DATETIME,
  last_validated_at DATETIME,
  is_valid INTEGER DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Backup history tracking
CREATE TABLE IF NOT EXISTS backup_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  backup_type TEXT NOT NULL,      -- full, incremental, manual, auto
  file_path TEXT NOT NULL,
  file_size INTEGER,
  record_count INTEGER,
  checksum TEXT,                  -- SHA256 hash for integrity verification
  is_encrypted INTEGER DEFAULT 0,
  is_compressed INTEGER DEFAULT 1,
  status TEXT DEFAULT 'completed', -- pending, completed, failed, restored
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Security events tracking
CREATE TABLE IF NOT EXISTS security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,       -- failed_login, rate_limit, suspicious_activity, data_export, permission_change
  severity TEXT NOT NULL DEFAULT 'info', -- info, warning, critical
  source TEXT,                    -- ip address or system
  description TEXT,
  metadata TEXT,                  -- JSON with extra context
  resolved INTEGER DEFAULT 0,
  resolved_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Access control list for fine-grained permissions
CREATE TABLE IF NOT EXISTS access_permissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collaborator_id INTEGER NOT NULL,
  resource_type TEXT NOT NULL,    -- project, task, report, settings
  resource_id TEXT,               -- specific resource ID or '*' for all
  permission TEXT NOT NULL,       -- read, write, delete, admin
  granted_by INTEGER,
  is_active INTEGER DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (collaborator_id) REFERENCES collaborators(id),
  FOREIGN KEY (granted_by) REFERENCES collaborators(id)
);

-- Seed default permissions for owner
INSERT OR IGNORE INTO access_permissions (collaborator_id, resource_type, resource_id, permission, granted_by)
SELECT id, 'project', '*', 'admin', id FROM collaborators WHERE role = 'owner' LIMIT 1;
