-- ─────────────────────────────────────────────────────────────────
-- cost_ledger — per-call paid-API cost log
-- ─────────────────────────────────────────────────────────────────
-- Replaces data/costs/cost_ledger.jsonl (append-only, full-scan reads).
-- Indexed by date + source for the daily-rollup hot path.
--
-- Source JSONL row shape (preserved):
--   { timestamp, date, source, amount_usd, category, detail, metadata }
--
-- Mapping:
--   timestamp   -> ts             (ISO 8601 UTC)
--   date        -> date_utc       (YYYY-MM-DD, indexed)
--   source      -> source         (e.g. "anthropic")
--   amount_usd  -> actual_cost_usd
--   category    -> purpose
--   detail      -> kept inside metadata.detail
--   metadata    -> metadata       (JSON blob — model, tokens, anything else)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cost_ledger (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT    NOT NULL,
    date_utc         TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    model            TEXT,
    purpose          TEXT,
    est_cost_usd     REAL,
    actual_cost_usd  REAL    NOT NULL,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    metadata         TEXT
);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_date
    ON cost_ledger(date_utc);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_source
    ON cost_ledger(source);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_date_source
    ON cost_ledger(date_utc, source);

-- Migration idempotency for the one-shot JSONL→SQLite tool:
-- (ts, source, actual_cost_usd) is unique enough that re-running the
-- migration on the same source file will INSERT OR IGNORE duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cost_ledger_dedup
    ON cost_ledger(ts, source, actual_cost_usd, purpose);
