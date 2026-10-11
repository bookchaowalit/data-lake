-- Migration 057: add one canonical weekly review task for diary, habits, and routines.
-- Daily habits remain in habit_logs and this task only owns the weekly operating decision.

INSERT INTO tasks (
    title, description, status, priority, project, tags, category, due_date,
    sync_status, estimated_minutes
)
SELECT
    'Personal Operating Review — diary, habits, and routines',
    'Review aggregate diary/journal metadata, habit_logs, and routine_logs for the weekly cycle. Do not copy raw diary or journal content. Acceptance: run npm --prefix infra run operating:personal-review -- --cycle adaptive-foundation-2026-w34 --write, inspect the generated evidence, and record one decision, one carryover, and the next action in the cycle review.',
    'todo', 2, 'book-operations',
    'operations,review,diary,habits,routines,governance', 'operations', '2026-08-23',
    'local', 60
WHERE NOT EXISTS (
    SELECT 1 FROM tasks
    WHERE title = 'Personal Operating Review — diary, habits, and routines'
);

INSERT OR IGNORE INTO task_project_links (
    task_id, project_id, relation_type, weight, source
)
SELECT t.id, p.id, 'supporting', 1, '057_personal_operating_review'
FROM tasks t
JOIN projects p ON p.slug = 'book-operations'
WHERE t.title = 'Personal Operating Review — diary, habits, and routines';

INSERT OR IGNORE INTO task_context_links (
    task_id, context_id, relation_type, weight, source
)
SELECT t.id, c.id, 'primary', 1, '057_personal_operating_review'
FROM tasks t
JOIN portfolio_contexts c ON c.slug = 'solo-empire-internal'
WHERE t.title = 'Personal Operating Review — diary, habits, and routines';

INSERT OR IGNORE INTO operating_cycle_tasks (
    cycle_id, task_id, commitment_type, estimate_minutes, evidence_required, notes
)
SELECT c.id, t.id, 'committed', 60, 1,
       'Governance gate: inspect aggregate diary, habit, and routine signals without copying private text.'
FROM operating_cycles c
JOIN tasks t ON t.title = 'Personal Operating Review — diary, habits, and routines'
WHERE c.slug = 'adaptive-foundation-2026-w34';

UPDATE operating_cycles
SET capacity_minutes = 660,
    notes = 'Active weekly cycle includes a 60-minute Personal Operating Review governance gate for diary, habits, and routines. AI is optional support, not a separate sprint type.'
WHERE slug = 'adaptive-foundation-2026-w34';
