-- ─────────────────────────────────────────────────────────────────
-- predictions — Awarebot + Council prediction outputs
-- ─────────────────────────────────────────────────────────────────
-- W8-A12 (2026-05-24): Migrates data/predictions/pred-*.json (and the
-- council/council-pred-*.json sibling) out of one-file-per-prediction
-- (786 JSON files at audit) into a single indexed table. Source files
-- remain on disk for the burn-in period — the migration is INSERT OR
-- REPLACE so re-running it picks up any new files dropped after the
-- last run.
--
-- Source JSON shape (pred-*.json from runtime.awarebot.predictor):
--   { "topic": "general",
--     "consensus": "[Consensus: ...] ```json {...} ``` [...]"  -- raw lead-model text
--     "confidence": 0.6081,
--     "convergence": ["Thematic convergence: ..."],   -- list[str]
--     "timestamp": "2026-05-20T00:30:52.333857+00:00",
--     "signal_count": 500 }
--
-- Council-pred file shape (council-pred-*.json):
--   { "id"|"prediction_id": str, "topic": str, "description": str,
--     "probability": float, "confidence": float, "direction": str,
--     "cited_sources": [...], "linked_signals": [...],
--     "models": [...], "outcome": null }
--
-- Column mapping:
--   id                    -> derived from the file stem when missing
--                            (pred-YYYYMMDD-HHMMSS / council-pred-...)
--   created_at            -> entry["timestamp"] || file mtime
--   topic                 -> entry["topic"]      (NULL if absent)
--   direction             -> entry["direction"]  (post-classified; iOS reads this)
--   probability           -> entry["probability"]
--   confidence            -> entry["confidence"]
--   description           -> entry["description"] || entry["consensus"]
--   cited_sources_json    -> json.dumps(entry["cited_sources"])
--   linked_signals_json   -> json.dumps(entry["linked_signals"] || [])
--   outcome               -> entry["outcome"]    (NULL until /prediction/{id}/outcome)
--   outcome_recorded_at   -> entry["outcome_recorded_at"]
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS predictions (
    id                   TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,        -- ISO 8601 UTC
    topic                TEXT,
    direction            TEXT,                 -- bullish/bearish/neutral/...
    probability          REAL,                 -- 0.0..1.0
    confidence           REAL,                 -- 0.0..1.0
    description          TEXT,                 -- cleaned prediction text
    cited_sources_json   TEXT,                 -- JSON array string
    linked_signals_json  TEXT,                 -- JSON array string
    outcome              TEXT,                 -- NULL until resolved
    outcome_recorded_at  TEXT                  -- ISO 8601 UTC when outcome stamped
);

-- Recent-first listing — drives GET /predictions and iOS Predictions tab.
CREATE INDEX IF NOT EXISTS idx_predictions_created
    ON predictions(created_at DESC);

-- Resolved-only scan — drives accuracy rollups (GET /prediction/accuracy).
-- Partial index keeps the resolved set lean even after 10K+ predictions.
CREATE INDEX IF NOT EXISTS idx_predictions_outcome
    ON predictions(outcome)
    WHERE outcome IS NOT NULL;

-- Per-topic filter — drives topic-scoped predictions and convergence views.
CREATE INDEX IF NOT EXISTS idx_predictions_topic
    ON predictions(topic);
