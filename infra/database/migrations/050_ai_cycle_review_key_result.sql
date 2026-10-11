-- Migration 050: ensure the review key result is present for the AI cadence objective.

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
