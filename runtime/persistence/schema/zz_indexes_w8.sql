-- ─────────────────────────────────────────────────────────────────
-- indexes_w8.sql — composite indexes for hot-path read patterns
-- ─────────────────────────────────────────────────────────────────
-- W8-A7 (2026-05-24): Adds the composite indexes the burn-in revealed
-- as bottlenecks on flipped-flag reads. Each individual column already
-- has its own index (idx_units_authority_tier, idx_units_importance,
-- idx_units_created, idx_council_sessions_pump base would not exist),
-- but the planner can only consult one per query. Composites let it
-- skip the sort phase on the working-context salience scan and the
-- pump-session lookup that runs on every iOS Strike-Point tap.
--
-- ALL indexes here are IF NOT EXISTS so re-applying this migration is
-- a no-op. The schema_migrations table records `indexes_w8.sql` once
-- and skips it on subsequent boots.
--
-- Read patterns these indexes accelerate:
--   1. working_context / chat_context: ORDER BY authority_tier DESC,
--      importance DESC LIMIT N — drives the working-context assembler
--      and salience-baked recall ranking.
--   2. memory timeline view: ORDER BY created_at DESC, importance DESC
--      LIMIT N — drives MemoryTimelineView pagination and the iOS
--      day-grouped timeline.
--   3. /pump/review/{id}: SELECT ... WHERE pump_id = ?
--      ORDER BY created_at DESC — drives iOS pump-status polling and
--      the merged Strike Point in-process flow result lookup.
-- ─────────────────────────────────────────────────────────────────

-- units_index composite — authority + importance ranking
-- Used by: working_context.py, chat_context.py, procedural.py,
-- conflict_resolver.py, dashboard_bridge.py, brain._maybe_indexed_search
CREATE INDEX IF NOT EXISTS idx_units_authority_importance
    ON units_index(authority_tier, importance DESC);

-- units_index composite — recency + importance ranking
-- Used by: MemoryTimelineView, eval/runner.py recall@N, staleness loop
CREATE INDEX IF NOT EXISTS idx_units_created_importance
    ON units_index(created_at DESC, importance DESC);

-- council_sessions composite — pump-id lookup with recency tiebreak
-- Used by: /pump/review/{id}, Brain auto_flow result hydration,
-- iOS Strike Point tab post-fire poll loop
CREATE INDEX IF NOT EXISTS idx_council_sessions_pump
    ON council_sessions(pump_prompt_id, created_at DESC);
