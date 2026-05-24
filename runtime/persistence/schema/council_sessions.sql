-- ─────────────────────────────────────────────────────────────────
-- council_sessions / council_rounds — multi-LLM debate logs
-- (DESIGNED, NOT YET MIGRATED — follow-up agent)
-- ─────────────────────────────────────────────────────────────────
-- Today's source of truth lives in data/councils/*.json plus the in-memory
-- CouncilSession object. The current bug surface (sessions stuck at status
-- DEBATING because the runner never persists the final state) is part of
-- why a real durable store is wanted here.
--
-- Two-table split:
--   council_sessions — one row per session, fast status/topic queries
--   council_rounds   — one row per round per panelist, for transcript
--                       reconstruction + dissent surfacing
--
-- Migration plan: see PERSISTENCE.md "Roadmap".
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS council_sessions (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    topic           TEXT NOT NULL,
    chair           TEXT,                       -- "claude" by default
    panelists       TEXT,                       -- JSON array of model ids
    status          TEXT NOT NULL,              -- DEBATING / COMPLETED / FAILED
    consensus       TEXT,
    dissent         TEXT,
    chair_summary   TEXT,
    next_steps      TEXT,                       -- JSON list
    cost_usd        REAL DEFAULT 0,
    pump_prompt_id  TEXT,
    mandate_id      TEXT,
    payload         TEXT                        -- full JSON session blob
);

CREATE INDEX IF NOT EXISTS idx_council_sessions_status   ON council_sessions(status);
CREATE INDEX IF NOT EXISTS idx_council_sessions_created  ON council_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_council_sessions_mandate  ON council_sessions(mandate_id);


CREATE TABLE IF NOT EXISTS council_rounds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    round_idx       INTEGER NOT NULL,
    panelist        TEXT NOT NULL,              -- claude / grok / gemini / gpt / perplexity
    role            TEXT,                       -- chair / member / dissenter
    content         TEXT,
    confidence      REAL,
    citations       TEXT,                       -- JSON array
    created_at      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES council_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_council_rounds_session ON council_rounds(session_id);
CREATE INDEX IF NOT EXISTS idx_council_rounds_panelist ON council_rounds(panelist);
