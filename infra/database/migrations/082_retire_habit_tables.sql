-- Retire the habit tables from the control plane (owner direction 2026-10-10,
-- one cell = one repo, backend and database). Habits, routines and their daily
-- logs live in the solo-habits cell (its own Neon database), and every reader
-- and writer goes through infra/scripts/utils/habits_store.py. The tables held
-- no rows at retirement and no other table references them. The old DDL lives
-- on for tests in infra/tests/support/legacy_habit_tables.sql.
-- Guard: refuse to drop data. A database that still holds habit rows fails here.
CREATE TEMP TABLE retire_habits_guard (rows_left INTEGER NOT NULL CHECK (rows_left = 0));
INSERT INTO retire_habits_guard SELECT (SELECT count(*) FROM habits) + (SELECT count(*) FROM habit_logs)
    + (SELECT count(*) FROM routines) + (SELECT count(*) FROM routine_logs);
DROP TABLE retire_habits_guard;
DROP TABLE IF EXISTS routine_logs;
DROP TABLE IF EXISTS routines;
DROP TABLE IF EXISTS habit_logs;
DROP TABLE IF EXISTS habits;
