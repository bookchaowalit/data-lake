-- Retire the local entity graph, the local AI telemetry and the skill progress log (owner decisions 2026-10-11).
-- - entity_registry, entity_links, entity_gap_reviews: a projection of cell data, repository files and git
--   commits. Cross-domain traceability now comes from the empire-platform graph that every cell publishes
--   to; the projection and its reports were deleted, not moved, so their rows are dropped on purpose.
-- - ai_run_telemetry, ai_prompt_cache, ai_conversation_logs: owned by bookchaowalit/solo-ai-gateway; the
--   local copies and their code were deleted.
-- - progress_log: moved to the roles-skills cell (resource progress-entry, migration 0002 there).
-- Guard: the AI tables and progress_log never held a row here; refuse to drop them if one appeared.
CREATE TEMP TABLE retire_graph_ai_progress_guard (rows_left INTEGER NOT NULL CHECK (rows_left = 0));
INSERT INTO retire_graph_ai_progress_guard SELECT
      (SELECT count(*) FROM ai_run_telemetry) + (SELECT count(*) FROM ai_prompt_cache)
    + (SELECT count(*) FROM ai_conversation_logs) + (SELECT count(*) FROM progress_log);
DROP TABLE retire_graph_ai_progress_guard;

DROP TABLE IF EXISTS entity_links;
DROP TABLE IF EXISTS entity_gap_reviews;
DROP TABLE IF EXISTS entity_registry;
DROP TABLE IF EXISTS ai_run_telemetry;
DROP TABLE IF EXISTS ai_prompt_cache;
DROP TABLE IF EXISTS ai_conversation_logs;
DROP TABLE IF EXISTS progress_log;
