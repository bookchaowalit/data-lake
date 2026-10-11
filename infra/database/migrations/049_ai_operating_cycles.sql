-- Migration 049: make AI work measurable before execution.
-- Goals remain the objective layer, these tables add relational key results,
-- AI-specific KPI definitions, sprint commitments, and review decisions.

CREATE TABLE IF NOT EXISTS goal_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    metric_type TEXT NOT NULL DEFAULT 'key_result'
        CHECK(metric_type IN ('key_result', 'kpi', 'guardrail')),
    direction TEXT NOT NULL DEFAULT 'increase'
        CHECK(direction IN ('increase', 'decrease', 'maintain')),
    unit TEXT NOT NULL DEFAULT 'count',
    baseline_value REAL,
    target_value REAL NOT NULL,
    current_value REAL,
    status TEXT NOT NULL DEFAULT 'no_data'
        CHECK(status IN ('no_data', 'on_track', 'at_risk', 'off_track', 'achieved')),
    source_type TEXT NOT NULL DEFAULT 'manual'
        CHECK(source_type IN ('manual', 'task', 'ai_telemetry', 'system')),
    source_ref TEXT,
    evidence_ref TEXT,
    period_start DATE,
    period_end DATE,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(goal_id, metric_key),
    CHECK(period_end IS NULL OR period_start IS NULL OR period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS ai_work_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    cycle_type TEXT NOT NULL DEFAULT 'sprint'
        CHECK(cycle_type IN ('sprint', 'weekly', 'planning', 'review')),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK(status IN ('planned', 'active', 'in_review', 'closed', 'cancelled')),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    focus TEXT NOT NULL,
    capacity_minutes INTEGER CHECK(capacity_minutes IS NULL OR capacity_minutes >= 0),
    owner TEXT NOT NULL DEFAULT 'Owner',
    decision TEXT
        CHECK(decision IS NULL OR decision IN ('continue', 'adjust', 'pause', 'close')),
    source TEXT NOT NULL DEFAULT 'ai-operating-cadence',
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS ai_cycle_goal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES ai_work_cycles(id) ON DELETE CASCADE,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'objective'
        CHECK(link_type IN ('objective', 'supporting', 'guardrail')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cycle_id, goal_id)
);

CREATE TABLE IF NOT EXISTS ai_cycle_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL REFERENCES ai_work_cycles(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    commitment_type TEXT NOT NULL DEFAULT 'committed'
        CHECK(commitment_type IN ('committed', 'stretch', 'carried_over', 'dropped')),
    estimate_minutes INTEGER CHECK(estimate_minutes IS NULL OR estimate_minutes >= 0),
    evidence_required INTEGER NOT NULL DEFAULT 1 CHECK(evidence_required IN (0, 1)),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cycle_id, task_id)
);

CREATE TABLE IF NOT EXISTS ai_kpi_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count',
    direction TEXT NOT NULL DEFAULT 'increase'
        CHECK(direction IN ('increase', 'decrease', 'maintain')),
    target_value REAL NOT NULL,
    source_kind TEXT NOT NULL
        CHECK(source_kind IN ('cycle_tasks', 'ai_telemetry', 'review', 'manual')),
    privacy_class TEXT NOT NULL DEFAULT 'internal'
        CHECK(privacy_class IN ('public', 'internal', 'private')),
    metric_group TEXT NOT NULL DEFAULT 'operating',
    measurement_cadence TEXT NOT NULL DEFAULT 'weekly',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'paused', 'retired')),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_kpi_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kpi_id INTEGER NOT NULL REFERENCES ai_kpi_definitions(id) ON DELETE CASCADE,
    cycle_id INTEGER NOT NULL REFERENCES ai_work_cycles(id) ON DELETE CASCADE,
    value REAL NOT NULL,
    target_value REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'no_data'
        CHECK(status IN ('no_data', 'on_track', 'at_risk', 'off_track', 'achieved')),
    measured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_ref TEXT,
    evidence_ref TEXT,
    metadata_json TEXT,
    UNIQUE(kpi_id, cycle_id)
);

CREATE TABLE IF NOT EXISTS ai_cycle_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL UNIQUE REFERENCES ai_work_cycles(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL DEFAULT 'Owner',
    summary TEXT NOT NULL,
    delivered_summary TEXT,
    carryover_summary TEXT,
    blocker_summary TEXT,
    learning_summary TEXT,
    decision TEXT NOT NULL
        CHECK(decision IN ('continue', 'adjust', 'pause', 'close')),
    evidence_ref TEXT,
    reviewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goal_metrics_goal_status
    ON goal_metrics(goal_id, status, metric_type);
CREATE INDEX IF NOT EXISTS idx_ai_work_cycles_status_dates
    ON ai_work_cycles(status, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_ai_cycle_goal_links_goal
    ON ai_cycle_goal_links(goal_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_ai_cycle_tasks_task
    ON ai_cycle_tasks(task_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_ai_kpi_measurements_cycle
    ON ai_kpi_measurements(cycle_id, measured_at DESC);

INSERT INTO goals (
    title, description, type, category, status, priority, start_date, due_date,
    progress_percent, key_results, notes, domain
)
SELECT
    'AI Operating System: evidence-backed delivery cadence',
    'Create a measurable AI operating loop before expanding learning or product execution.',
    'quarterly', 'tech', 'active', 1, '2026-08-17', '2026-09-30', 0,
    '["Run planned work through an explicit AI cycle", "Measure delivery, telemetry, cost, and quality signals", "Complete a review before carrying work into the next cycle"]',
    'System-control objective, execution remains subject to owner review and approval.',
    'book-ai'
WHERE NOT EXISTS (
    SELECT 1 FROM goals
    WHERE title = 'AI Operating System: evidence-backed delivery cadence'
      AND domain = 'book-ai'
);

INSERT OR IGNORE INTO goal_metrics (
    goal_id, metric_key, name, description, metric_type, direction, unit,
    baseline_value, target_value, current_value, status, source_type,
    source_ref, period_start, period_end, notes
)
SELECT g.id, 'explicit-cycle', 'Explicit AI cycle exists',
       'At least one planned or active cycle owns the work before execution.',
       'key_result', 'increase', 'cycles', 0, 1, 0, 'no_data', 'manual',
       'ai_work_cycles', '2026-08-17', '2026-09-30',
       'The cycle must be reviewed by the owner before work starts.'
FROM goals g
WHERE g.title = 'AI Operating System: evidence-backed delivery cadence'
  AND g.domain = 'book-ai';

INSERT OR IGNORE INTO goal_metrics (
    goal_id, metric_key, name, description, metric_type, direction, unit,
    baseline_value, target_value, current_value, status, source_type,
    source_ref, period_start, period_end, notes
)
SELECT g.id, 'review-completion', 'Cycle review completion',
       'Every closed cycle has an explicit retrospective and next decision.',
       'key_result', 'increase', '%', 0, 100, 0, 'no_data', 'manual',
       'ai_cycle_reviews', '2026-08-17', '2026-09-30',
       'No cycle is considered complete without a review record.'
FROM goals g
WHERE g.title = 'AI Operating System: evidence-backed delivery cadence'
  AND g.domain = 'book-ai';

INSERT OR IGNORE INTO goal_metrics (
    goal_id, metric_key, name, description, metric_type, direction, unit,
    baseline_value, target_value, current_value, status, source_type,
    source_ref, period_start, period_end, notes
)
SELECT g.id, 'evidence-backed-delivery', 'Evidence-backed delivery',
       'Committed work produces a reviewable artifact or explicit accepted exception.',
       'key_result', 'increase', '%', 0, 100, 0, 'no_data', 'task',
       'ai_cycle_tasks', '2026-08-17', '2026-09-30',
       'The system does not infer completion from a checklist alone.'
FROM goals g
WHERE g.title = 'AI Operating System: evidence-backed delivery cadence'
  AND g.domain = 'book-ai';

INSERT OR IGNORE INTO ai_work_cycles (
    slug, name, cycle_type, status, start_date, end_date, focus,
    capacity_minutes, owner, source, notes
)
VALUES (
    'ai-foundation-2026-w34',
    'AI Foundation and Systems Learning Control Sprint',
    'sprint', 'planned', '2026-08-17', '2026-08-23',
    'Establish the control loop, then execute only evidence-backed OS, protocol, and networking work.',
    600, 'Owner', 'ai-operating-cadence',
    'Planned only. Start explicitly after reviewing objective, capacity, KPI guardrails, and task commitment.'
);

INSERT OR IGNORE INTO ai_cycle_goal_links (cycle_id, goal_id, link_type)
SELECT c.id, g.id, 'objective'
FROM ai_work_cycles c
JOIN goals g ON g.title = 'AI Operating System: evidence-backed delivery cadence'
             AND g.domain = 'book-ai'
WHERE c.slug = 'ai-foundation-2026-w34';

INSERT OR IGNORE INTO ai_cycle_tasks (
    cycle_id, task_id, commitment_type, estimate_minutes, evidence_required, notes
)
SELECT c.id, t.id, 'committed', t.estimated_minutes, 1,
       'Execution is gated by starting the planned AI cycle.'
FROM ai_work_cycles c
JOIN tasks t ON t.project = 'systems-networking-lab'
WHERE c.slug = 'ai-foundation-2026-w34';

INSERT OR IGNORE INTO ai_kpi_definitions (
    slug, name, description, unit, direction, target_value, source_kind, notes
)
VALUES
    ('cycle-delivery-rate', 'Cycle delivery rate',
     'Percentage of committed cycle tasks completed with acceptance.', '%', 'increase', 80,
     'cycle_tasks', 'Target is a planning guardrail, not permission to mark incomplete work done.'),
    ('cycle-commitment-accuracy', 'Cycle commitment accuracy',
     'Completed committed minutes divided by committed minutes.', '%', 'increase', 80,
     'cycle_tasks', 'Use estimates as planning signals and review large variance.'),
    ('ai-telemetry-success-rate', 'AI telemetry success rate',
     'Successful AI runs divided by recorded AI runs in the cycle window.', '%', 'increase', 95,
     'ai_telemetry', 'No provider run is treated as no_data, not as success.'),
    ('ai-budget-compliance', 'AI budget compliance',
     'AI runs without budget_exceeded status divided by recorded AI runs.', '%', 'increase', 100,
     'ai_telemetry', 'Counts and metadata only, prompts and responses are never stored.'),
    ('ai-cost-usd', 'AI cost guardrail',
     'Estimated AI provider cost during the cycle window.', 'USD', 'decrease', 5,
     'ai_telemetry', 'Adjust after an owner-approved provider and budget decision.'),
    ('cycle-review-complete', 'Cycle review completion',
     'Whether the cycle has a recorded retrospective and next decision.', '%', 'increase', 100,
     'review', 'A closed cycle without review is invalid.'),
    ('evidence-gate-rate', 'Evidence gate rate',
     'Percentage of committed tasks with reviewable evidence or an accepted exception.', '%', 'increase', 100,
     'manual', 'Requires owner review, the system does not infer evidence from task status.');
