-- Retire the decision tables from the control plane (owner direction 2026-10-10:
-- one cell = one repo, backend and database). Decisions, their lifecycle events
-- and reviews live in the solo-decisions cell (its own Neon database), every
-- reader and writer goes through infra/scripts/utils/decision_store.py. The
-- tables held no rows at retirement, and no other table references them.
-- The old DDL survives for tests in infra/tests/support/legacy_decision_tables.sql.
-- Guard: refuse to drop data. A database that still holds decision rows fails here,
-- move them to the decisions cell first.
CREATE TEMP TABLE retire_decisions_guard (rows_left INTEGER NOT NULL CHECK (rows_left = 0));
INSERT INTO retire_decisions_guard SELECT (SELECT count(*) FROM decision_records)
    + (SELECT count(*) FROM decision_events) + (SELECT count(*) FROM decision_reviews);
DROP TABLE retire_decisions_guard;
DROP TABLE IF EXISTS decision_reviews;
DROP TABLE IF EXISTS decision_events;
DROP TABLE IF EXISTS decision_records;
