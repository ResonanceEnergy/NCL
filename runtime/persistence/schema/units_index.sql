-- ─────────────────────────────────────────────────────────────────
-- units_index — lightweight index over the MemoryStore (DESIGNED, NOT MIGRATED)
-- ─────────────────────────────────────────────────────────────────
-- Important: the full MemUnit body stays in data/memory/units.jsonl + ChromaDB.
-- This table is JUST an index — id, timestamps, importance, authority, tags,
-- and chroma_collection — so the working-context assembler and the iOS
-- Memory tab can do filtered/ranked queries WITHOUT scanning the whole 200MB
-- JSONL on every request.
--
-- The unit body is fetched by id from JSONL (cheap, since you already
-- know the byte offset is approximately the row order — or you can do a
-- single Chroma GET by id). Chroma stays the home for the vector.
--
-- Why an index instead of full migration:
--   * units.jsonl is the largest store (~25K units, 200MB compaction).
--   * MemoryStore is the highest-risk migration — touching it without
--     a separate dedicated agent + full eval-harness pass is reckless.
--   * An index gives 80% of the win (fast filtered reads) for 20% of
--     the risk: writes stay double, reads start to use SQL.
--
-- W4-14 (2026-05-23): aligned column names to MemUnit Pydantic model
-- (unit_id, last_accessed, authority_tier as INTEGER 10..100) and added
-- content_hash, source, reinforcement_count, decay_rate to match the
-- on-disk MemUnit shape. The legacy decay_score / tier / chroma_collection
-- / signal_id / fingerprint columns remain for the optional metadata
-- the migration script can populate when available.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS units_index (
    unit_id              TEXT PRIMARY KEY,
    content_hash         TEXT,                       -- sha256(content[:1000]) for dedup
    source               TEXT,                       -- e.g. 'awarebot', 'council:CS-...', 'first-strike-chat'
    memory_type          TEXT NOT NULL,              -- episodic/semantic/procedural/signal/decision/preference
    authority_tier       INTEGER NOT NULL,           -- 10..100 (NATRIX=100 / COUNCIL=80 / BRAIN=60 / CALENDAR=50 / LLM_SINGLE=40 / SCANNER=20 / RAW=10)
    importance           REAL NOT NULL,              -- 0..100
    created_at           TEXT NOT NULL,              -- ISO8601 UTC
    last_accessed        TEXT,                       -- ISO8601 UTC, nullable
    tags                 TEXT,                       -- JSON array (string for LIKE-search via idx_units_tags)
    reinforcement_count  INTEGER NOT NULL DEFAULT 0,
    decay_rate           REAL NOT NULL DEFAULT 0.95,
    -- Optional (best-effort population by migration / double-write):
    decay_score          REAL,                       -- current FadeMem value
    tier                 TEXT,                       -- focused/micro/macro (signal routing)
    chroma_collection    TEXT,                       -- ncl_episodic / ncl_semantic / ...
    signal_id            TEXT,                       -- back-ref to source signal if applicable
    fingerprint          TEXT                        -- SHA1 of content for legacy dedup
);

CREATE INDEX IF NOT EXISTS idx_units_source        ON units_index(source);
CREATE INDEX IF NOT EXISTS idx_units_memory_type   ON units_index(memory_type);
CREATE INDEX IF NOT EXISTS idx_units_authority_tier ON units_index(authority_tier);
CREATE INDEX IF NOT EXISTS idx_units_created       ON units_index(created_at);
CREATE INDEX IF NOT EXISTS idx_units_importance    ON units_index(importance);
-- tags is stored as a JSON array string; queries use LIKE '%"tagname"%' for
-- substring containment. Indexing the column lets SQLite skip the table
-- scan when a prefix is present and gives a sortable order for diagnostics.
CREATE INDEX IF NOT EXISTS idx_units_tags          ON units_index(tags);
CREATE INDEX IF NOT EXISTS idx_units_fingerprint   ON units_index(fingerprint);
CREATE INDEX IF NOT EXISTS idx_units_signal        ON units_index(signal_id);
