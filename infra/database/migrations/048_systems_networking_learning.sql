-- Migration 048: Systems, OS, protocol, and networking learning project.
-- This migration registers the missing protocol skill and creates an honest,
-- planned project with local-only execution tasks. It never marks learning done.

INSERT OR IGNORE INTO skills (
    name, slug, description, category_id, target_level, priority, status,
    progress_percent, key_concepts, resources, notes
)
SELECT
    'Protocol Engineering',
    'protocol-engineering',
    'Designs, explains, tests, and operates protocols through message contracts, state, failure, versioning, and compatibility.',
    id,
    'L1_deep',
    1,
    'not_started',
    0,
    '["layering","message contracts","state machines","timeouts","retry","compatibility","HTTP","DNS","TLS","Kafka","MCP"]',
    '["learning/systems-networking/README.md","learning/systems-networking/labs/README.md"]',
    'Created by the systems networking learning project, progress requires reviewable evidence.'
FROM skill_categories
WHERE slug = 'infrastructure';

UPDATE skills
SET resources = '["learning/systems-networking/README.md","learning/systems-networking/labs/README.md"]'
WHERE slug IN ('operating-systems', 'linux', 'networking', 'distributed-systems')
  AND (resources IS NULL OR resources = '');

INSERT OR IGNORE INTO projects (
    name, slug, description, category, type, status, priority, progress_percent,
    phase, docs_url, notes, domain
)
VALUES (
    'Systems Networking Lab',
    'systems-networking-lab',
    'Local evidence project connecting OS/Linux fundamentals to protocols, networking, and distributed-system operations.',
    'portfolio',
    'learning-lab',
    'planning',
    2,
    0,
    'curriculum-baseline',
    'learning/systems-networking/README.md',
    'Local-only Docker/K3s/homelab project. No public scanning, production apply, or automatic skill progress.',
    'book-learning'
);

UPDATE projects
SET parent_project_id = (SELECT id FROM projects WHERE slug = 'book-learning')
WHERE slug = 'systems-networking-lab' AND parent_project_id IS NULL;

INSERT OR IGNORE INTO project_context_links (project_id, context_id, relation_type, weight, source)
SELECT p.id, c.id, 'primary', 1, '048_systems_networking_learning'
FROM projects p
JOIN portfolio_contexts c ON c.slug = 'workspace-book-learning'
WHERE p.slug = 'systems-networking-lab';

INSERT INTO tasks (title, description, status, priority, project, tags, category, sync_status, estimated_minutes)
SELECT
    'Systems Networking Lab — OS/Linux baseline',
    'Complete the OS/Linux baseline: process, memory, filesystem, syscall, cgroups, and namespaces. Acceptance: read-only observations plus a host/container/guest boundary note.',
    'todo', 2, 'systems-networking-lab',
    'systems,operating-systems,linux,learning', 'learning', 'local', 120
WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE title = 'Systems Networking Lab — OS/Linux baseline');

INSERT INTO tasks (title, description, status, priority, project, tags, category, sync_status, estimated_minutes)
SELECT
    'Systems Networking Lab — Protocol map and contract notes',
    'Create protocol cards for TCP, UDP, DNS, HTTP, TLS, Kafka/Avro, and MCP. Acceptance: each card has message, state, timeout, retry, idempotency, version, and failure behavior.',
    'todo', 2, 'systems-networking-lab',
    'systems,protocol,networking,api,learning', 'learning', 'local', 150
WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE title = 'Systems Networking Lab — Protocol map and contract notes');

INSERT INTO tasks (title, description, status, priority, project, tags, category, sync_status, estimated_minutes)
SELECT
    'Systems Networking Lab — Local networking and packet evidence',
    'Run the local-only DNS/HTTP/TLS and K3s service-network observation lab. Acceptance: topology, DNS/HTTP/TLS trace summary, service discovery path, and NetworkPolicy observation.',
    'todo', 2, 'systems-networking-lab',
    'systems,networking,dns,tls,kubernetes,learning', 'learning', 'local', 150
WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE title = 'Systems Networking Lab — Local networking and packet evidence');

INSERT INTO tasks (title, description, status, priority, project, tags, category, sync_status, estimated_minutes)
SELECT
    'Systems Networking Lab — Distributed failure drill and portfolio evidence',
    'Run a synthetic timeout, retry, duplicate-event, or dependency-unavailable drill. Acceptance: expected/actual behavior, metric summary, recovery runbook, and Verified/Observed/Planned case study.',
    'todo', 3, 'systems-networking-lab',
    'systems,distributed-systems,reliability,observability,learning', 'learning', 'local', 180
WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE title = 'Systems Networking Lab — Distributed failure drill and portfolio evidence');

INSERT OR IGNORE INTO task_project_links (task_id, project_id, relation_type, weight, source)
SELECT t.id, p.id, 'delivery', 1, '048_systems_networking_learning'
FROM tasks t
JOIN projects p ON p.slug = 'systems-networking-lab'
WHERE t.project = 'systems-networking-lab';

INSERT OR IGNORE INTO task_context_links (task_id, context_id, relation_type, weight, source)
SELECT t.id, c.id, 'primary', 1, '048_systems_networking_learning'
FROM tasks t
JOIN portfolio_contexts c ON c.slug = 'workspace-book-learning'
WHERE t.project = 'systems-networking-lab';
