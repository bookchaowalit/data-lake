-- Retire the tables of the domains that never held rows here (owner direction 2026-10-11): content,
-- learning challenges, journal, health metrics and time tracking moved to empty cells made with
-- solo-cell-kit (solo-content, solo-learning, solo-diary, solo-health, solo-time) and their old local
-- code was deleted, not converted. business_kpis and business_health_snapshots had no code at all.
-- opportunities and opportunity_actions stay until the CRM move (the Frappe Lead projection reads them);
-- progress_log stays (the roles-skills evidence gates use it).
-- Guard: refuse to drop anything that holds a row; such a domain needs an import, not a drop.
CREATE TEMP TABLE retire_empty_domains_guard (rows_left INTEGER NOT NULL CHECK (rows_left = 0));
INSERT INTO retire_empty_domains_guard SELECT
      (SELECT count(*) FROM content) + (SELECT count(*) FROM content_calendar)
    + (SELECT count(*) FROM content_series_episodes) + (SELECT count(*) FROM content_series_episode_metrics)
    + (SELECT count(*) FROM learning_challenges) + (SELECT count(*) FROM learning_challenge_assignments)
    + (SELECT count(*) FROM journal) + (SELECT count(*) FROM health_metrics)
    + (SELECT count(*) FROM time_entries) + (SELECT count(*) FROM time_logs)
    + (SELECT count(*) FROM business_kpis) + (SELECT count(*) FROM business_health_snapshots);
DROP TABLE retire_empty_domains_guard;

DROP TABLE IF EXISTS content_series_episode_metrics;
DROP TABLE IF EXISTS content_series_episodes;
DROP TABLE IF EXISTS content_calendar;
DROP TABLE IF EXISTS content;
DROP TABLE IF EXISTS learning_challenge_assignments;
DROP TABLE IF EXISTS learning_challenges;
DROP TABLE IF EXISTS journal;
DROP TABLE IF EXISTS health_metrics;
DROP TABLE IF EXISTS time_entries;
DROP TABLE IF EXISTS time_logs;
DROP TABLE IF EXISTS business_health_snapshots;
DROP TABLE IF EXISTS business_kpis;
