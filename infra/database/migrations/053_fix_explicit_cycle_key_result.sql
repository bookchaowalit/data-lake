-- Migration 053: restore the explicit-cycle Key Result label after the scoped repair.

UPDATE goal_metrics
SET name = 'Explicit operating cycle exists',
    description = 'At least one planned or active portfolio cycle owns the work before execution.',
    source_ref = 'operating_cycles'
WHERE metric_key = 'explicit-cycle';
