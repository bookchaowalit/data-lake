-- Migration 051: generalize the AI-only operating cycle into a portfolio cycle.
-- The 049 tables are retained as historical migration names; this migration
-- moves their live data to the provider-neutral operating-cycle contract.

DROP INDEX IF EXISTS idx_operating_cycles_status_dates;
DROP INDEX IF EXISTS idx_operating_cycle_goal_links_goal;
DROP INDEX IF EXISTS idx_operating_cycle_tasks_task;
DROP INDEX IF EXISTS idx_operating_kpi_measurements_cycle;

DROP TABLE IF EXISTS operating_cycle_reviews;
DROP TABLE IF EXISTS operating_kpi_measurements;
DROP TABLE IF EXISTS operating_cycle_tasks;
DROP TABLE IF EXISTS operating_cycle_goal_links;
DROP TABLE IF EXISTS operating_kpi_definitions;
DROP TABLE IF EXISTS operating_cycles;

ALTER TABLE ai_work_cycles RENAME TO operating_cycles;
ALTER TABLE ai_cycle_goal_links RENAME TO operating_cycle_goal_links;
ALTER TABLE ai_cycle_tasks RENAME TO operating_cycle_tasks;
ALTER TABLE ai_kpi_definitions RENAME TO operating_kpi_definitions;
ALTER TABLE ai_kpi_measurements RENAME TO operating_kpi_measurements;
ALTER TABLE ai_cycle_reviews RENAME TO operating_cycle_reviews;

ALTER TABLE operating_kpi_definitions ADD COLUMN metric_group TEXT NOT NULL DEFAULT 'operating';
ALTER TABLE operating_kpi_definitions ADD COLUMN measurement_cadence TEXT NOT NULL DEFAULT 'weekly';

CREATE INDEX IF NOT EXISTS idx_operating_cycles_status_dates
    ON operating_cycles(status, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_operating_cycle_goal_links_goal
    ON operating_cycle_goal_links(goal_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_operating_cycle_tasks_task
    ON operating_cycle_tasks(task_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_operating_kpi_measurements_cycle
    ON operating_kpi_measurements(cycle_id, measured_at DESC);

UPDATE goal_metrics
SET source_ref = CASE source_ref
    WHEN 'ai_work_cycles' THEN 'operating_cycles'
    WHEN 'ai_cycle_tasks' THEN 'operating_cycle_tasks'
    WHEN 'ai_cycle_reviews' THEN 'operating_cycle_reviews'
    ELSE source_ref
END
WHERE source_ref IN ('ai_work_cycles', 'ai_cycle_tasks', 'ai_cycle_reviews');

UPDATE goals
SET title = 'Adaptive Portfolio Operating System: evidence-backed delivery cadence',
    domain = 'book-operations',
    description = 'Run learning, product, operations, and AI-assisted work through short outcome-based cycles with explicit evidence, quality, cost, and risk review.',
    notes = 'Portfolio control objective. AI is a capability and measurement layer, not a separate sprint system.'
WHERE title = 'AI Operating System: evidence-backed delivery cadence'
  AND domain = 'book-ai';

UPDATE goal_metrics
SET name = 'Explicit operating cycle exists',
    description = 'At least one planned or active portfolio cycle owns the work before execution.',
    source_ref = 'operating_cycles'
WHERE metric_key = 'explicit-cycle';

UPDATE goal_metrics
SET name = 'Operating cycle review completion',
    description = 'Every closed portfolio cycle has an explicit retrospective and next decision.',
    source_ref = 'operating_cycle_reviews'
WHERE metric_key = 'review-completion';

UPDATE goal_metrics
SET name = 'Evidence-backed portfolio delivery',
    description = 'Committed work produces a reviewable artifact or explicit accepted exception.',
    source_ref = 'operating_cycle_tasks'
WHERE metric_key = 'evidence-backed-delivery';

UPDATE operating_cycles
SET slug = 'adaptive-foundation-2026-w34',
    name = 'Adaptive Portfolio Foundation Cycle',
    cycle_type = 'weekly',
    focus = 'Establish a weekly outcome, flow, quality, cost, and risk control loop before expanding portfolio work.',
    source = 'adaptive-portfolio-cadence',
    notes = 'Planned only. Start explicitly after reviewing the objective, capacity, KPI guardrails, and task commitment.'
WHERE slug = 'ai-foundation-2026-w34';

UPDATE operating_kpi_definitions
SET metric_group = CASE
        WHEN slug IN ('cycle-delivery-rate', 'cycle-commitment-accuracy', 'cycle-carryover-rate') THEN 'flow'
        WHEN slug IN ('cycle-review-complete', 'evidence-gate-rate') THEN 'governance'
        WHEN slug IN ('ai-eval-pass-rate', 'ai-human-acceptance-rate') THEN 'ai-quality'
        WHEN slug IN ('ai-telemetry-success-rate', 'ai-budget-compliance', 'ai-cost-usd', 'ai-cost-per-accepted-outcome') THEN 'ai-economics'
        WHEN slug IN ('ai-safety-incident-rate') THEN 'risk'
        ELSE 'outcome'
    END,
    measurement_cadence = CASE
        WHEN source_kind = 'ai_telemetry' THEN 'per-run-and-weekly'
        WHEN source_kind = 'review' THEN 'cycle-close'
        ELSE 'weekly'
    END;

UPDATE operating_kpi_definitions
SET name = 'Portfolio delivery rate',
    description = 'Percentage of committed cycle tasks completed and accepted.',
    notes = 'A flow signal, not a reason to mark incomplete work done.'
WHERE slug = 'cycle-delivery-rate';

UPDATE operating_kpi_definitions
SET name = 'Portfolio commitment accuracy',
    description = 'Completed committed minutes divided by committed minutes.',
    notes = 'Use estimates as planning signals and review large variance.'
WHERE slug = 'cycle-commitment-accuracy';

UPDATE operating_kpi_definitions
SET name = 'Operating cycle review completion',
    description = 'Whether the cycle has a recorded retrospective and next decision.'
WHERE slug = 'cycle-review-complete';

INSERT OR IGNORE INTO operating_kpi_definitions
    (slug, name, description, unit, direction, target_value, source_kind, metric_group, measurement_cadence, notes)
VALUES
    ('cycle-carryover-rate', 'Cycle carryover rate',
     'Percentage of committed work carried into a later cycle.', '%', 'decrease', 20,
     'cycle_tasks', 'flow', 'weekly', 'Set the target after two or three baseline cycles.'),
    ('ai-eval-pass-rate', 'AI evaluation pass rate',
     'Percentage of contextual AI evaluations meeting the accepted quality criteria.', '%', 'increase', 90,
     'manual', 'ai-quality', 'per-change-and-weekly', 'Requires a task-specific golden set or evaluation record.'),
    ('ai-human-acceptance-rate', 'AI human acceptance rate',
     'Percentage of reviewed AI outputs accepted without material correction.', '%', 'increase', 80,
     'manual', 'ai-quality', 'weekly', 'Do not infer acceptance from generation or task completion.'),
    ('ai-cost-per-accepted-outcome', 'AI cost per accepted outcome',
     'Estimated AI cost divided by accepted outcomes.', 'USD', 'decrease', 1,
     'ai_telemetry', 'ai-economics', 'weekly', 'Requires accepted-outcome and provider usage evidence.'),
    ('ai-safety-incident-rate', 'AI safety incident rate',
     'Percentage of AI-assisted outcomes requiring a safety, privacy, or security incident response.', '%', 'decrease', 0,
     'manual', 'risk', 'per-event-and-weekly', 'High-severity incidents are a stop-and-review signal.');
