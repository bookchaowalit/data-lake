-- Migration 052: repair the scoped Key Result labels from migration 051.

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
