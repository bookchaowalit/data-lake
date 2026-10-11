-- Migration 054: remove historical AI-only index names after table generalization.

DROP INDEX IF EXISTS idx_ai_work_cycles_status_dates;
DROP INDEX IF EXISTS idx_ai_cycle_goal_links_goal;
DROP INDEX IF EXISTS idx_ai_cycle_tasks_task;
DROP INDEX IF EXISTS idx_ai_kpi_measurements_cycle;

CREATE INDEX IF NOT EXISTS idx_operating_cycles_status_dates
    ON operating_cycles(status, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_operating_cycle_goal_links_goal
    ON operating_cycle_goal_links(goal_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_operating_cycle_tasks_task
    ON operating_cycle_tasks(task_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_operating_kpi_measurements_cycle
    ON operating_kpi_measurements(cycle_id, measured_at DESC);
