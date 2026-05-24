-- ─────────────────────────────────────────────────────────────────
-- mandates — Brain-internal council outputs
-- ─────────────────────────────────────────────────────────────────
-- Source of truth today is data/mandates.json plus the in-memory dict
-- in NCLBrain. SQLite is shipped as a double-write target behind the
-- env flag NCL_MANDATES_SQLITE (default OFF). After a 1-2 week burn-in
-- the read path will flip and the JSON file will be retired.
--
-- Column choices match the Mandate Pydantic model in
-- runtime/ncl_brain/models.py:Mandate so the migration script can do a
-- straight projection. `payload` carries the full Pydantic dump for
-- lossless round-tripping (e.g. arbitrary keys in `resources`).
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mandates (
    mandate_id          TEXT PRIMARY KEY,           -- e.g. MANDATE-2026-008
    pillar              TEXT,                       -- PillarType enum value (NCL/NCC/...)
    priority            INTEGER,                    -- 1-10 in current model
    title               TEXT,
    objective           TEXT,
    success_criteria    TEXT,                       -- JSON list[str]
    deadline            TEXT,                       -- ISO8601, nullable
    resources           TEXT,                       -- JSON dict
    status              TEXT NOT NULL,              -- MandateStatus value
    version             INTEGER NOT NULL DEFAULT 0, -- optimistic-lock counter
    created_at          TEXT NOT NULL,              -- ISO8601 UTC
    updated_at          TEXT NOT NULL,              -- ISO8601 UTC
    source_pump_id      TEXT,                       -- nullable; originating pump prompt
    status_history      TEXT,                       -- JSON list[dict]
    payload             TEXT NOT NULL               -- full Pydantic dump for round-trip safety
);

CREATE INDEX IF NOT EXISTS idx_mandates_status  ON mandates(status);
CREATE INDEX IF NOT EXISTS idx_mandates_pillar  ON mandates(pillar);
CREATE INDEX IF NOT EXISTS idx_mandates_created ON mandates(created_at);
CREATE INDEX IF NOT EXISTS idx_mandates_pump    ON mandates(source_pump_id);
