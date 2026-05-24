# NCL Persistence Layer — SQLite Foundation

**Status**: Wave 2 — foundation shipped 2026-05-23. Cost ledger is the first
(and currently only) double-written store. Mandates, council sessions, and
the MemoryStore units index are designed but not migrated.

---

## Why SQLite (not Postgres, not "just more JSONL")

NCL is single-node: a Mac Studio M1 Ultra running one Brain process plus a
few sidecars. The persistence pains we actually hit are:

- **Torn writes / partial flushes** on the 50+ hand-rolled JSONL appenders.
- **Full-file scans on 200MB ledgers** — the cost-ledger replay walks
  `cost_ledger.jsonl` line-by-line on every restart. The 30MB
  `contradicts_index.jsonl` had to be hard-capped at 5MB after OOM scares.
- **No atomic txns** — `mandates.json` rewrites the whole file on every
  mandate update. A crash mid-write is a corruption event.
- **No indexes** — every "show me today's spend by source" or "list pending
  mandates" rolls up via Python iteration over the entire file.

What we DON'T need:
- Multi-node replication. NCL is a personal-AI brain, not a SaaS.
- A separate DB process. Crash-recovery and ops surface area should stay
  near zero.
- An ORM. The data shapes are simple JSON-mostly blobs with a few hot
  query columns.

SQLite with WAL gives us:
- Atomic transactions, crash-safe by default.
- Indexed B-trees — daily rollups become an indexed `WHERE date_utc = ?`.
- Concurrent reads while a write is in flight (WAL).
- Zero ops — it's a file. `cp ncl.db ncl.db.bak` is a backup.
- Native to Python's stdlib — no new dependency to vendor.

**ChromaDB stays.** It owns the vector embeddings. SQLite owns relational,
audit, and lookup-heavy data. No overlap.

---

## Architecture

```
data/persistence/ncl.db          ← single SQLite file (WAL)
runtime/persistence/
  __init__.py                    ← exports SqliteStore, get_store
  sqlite_store.py                ← connection, lock, migrations, helpers
  schema/
    cost_ledger.sql              ← APPLIED (Wave 2)
    mandates.sql                 ← designed, NOT migrated
    council_sessions.sql         ← designed, NOT migrated
    units_index.sql              ← designed, NOT migrated
  migrations/
    001_create_cost_ledger.py    ← Python hook (most schemas don't need one)
scripts/
  migrate_cost_ledger_to_sqlite.py  ← one-shot, idempotent JSONL→SQLite
```

### SqliteStore (`runtime/persistence/sqlite_store.py`)

Single shared SQLite connection guarded by `asyncio.Lock`. Pragmas:

| Pragma             | Value   | Why                                        |
| ------------------ | ------- | ------------------------------------------ |
| `journal_mode`     | `WAL`   | Concurrent readers + one writer            |
| `synchronous`      | `NORMAL`| fsync on checkpoint, not on every commit   |
| `foreign_keys`     | `ON`    | Cheap safety                               |
| `busy_timeout`     | `5000`  | Tolerate long migrations under writer load |

API surface:

```python
store = await get_store()

# Single statement, auto-commit:
await store.execute_one("INSERT INTO cost_ledger (...) VALUES (...)", row)

# Bulk insert in one transaction:
await store.execute_many(sql, rows)

# Read:
rows = await store.fetch_all("SELECT ... WHERE date_utc = ?", (today,))
row  = await store.fetch_one(sql, params)

# Manual transaction control:
async with store.acquire("write") as conn:
    conn.execute("BEGIN")
    conn.execute("INSERT ...")
    conn.execute("UPDATE ...")
    conn.execute("COMMIT")
```

`db_path` defaults to `data/persistence/ncl.db`. Override at the env
level with `NCL_SQLITE_PATH=/some/other/path` (used in tests, never in
production).

### Schema migrations

- Every `*.sql` file in `runtime/persistence/schema/` is applied once at
  `SqliteStore.initialize()`.
- Applied files are recorded by name in the `schema_migrations` table.
- Files are processed in **lex order** — prefix new schemas with a number
  if ordering matters (`002_…sql`, `003_…sql`).
- **Do not edit an applied .sql file in place.** Ship a follow-up file
  that does `ALTER TABLE` / `CREATE INDEX` instead.
- `migrations/NNN_*.py` exists only when a schema change needs code-side
  post-processing (e.g., backfilling a column from another store).

### Adding a new schema

1. Drop `NNN_<name>.sql` into `runtime/persistence/schema/`.
2. (Optional) Add `runtime/persistence/migrations/NNN_<verb>.py` if you
   need a code hook.
3. Next call to `SqliteStore.initialize()` applies it. Existing rows in
   `schema_migrations` are preserved — the new file is just one more entry.

---

## Schema overview

### `cost_ledger` (LIVE, schema applied 2026-05-23)
Mirror of `data/costs/cost_ledger.jsonl`. Indexed on `(date_utc)`,
`(source)`, and `(date_utc, source)`. A UNIQUE index on
`(ts, source, actual_cost_usd, purpose)` makes the migration idempotent.

### `mandates` (designed, not migrated)
One row per mandate, status indexed for the pending-mandate hot path.
`payload` holds the full mandate JSON.

### `council_sessions` + `council_rounds` (designed, not migrated)
Two-table split: sessions for status/topic queries, rounds for transcript
reconstruction. Foreign key on `session_id`.

### `units_index` (designed, not migrated)
**Important**: this is an INDEX over the MemoryStore, not the full store.
The unit body stays in `units.jsonl` + ChromaDB. This table holds just the
columns the working-context assembler and iOS Memory tab filter on
(timestamps, importance, authority_tier, memory_type, fingerprint, tags).

---

## Roadmap

| Order | Store              | Risk   | Why this order                                            |
| ----- | ------------------ | ------ | --------------------------------------------------------- |
|   1   | `cost_ledger`      | LOW    | Append-only, single writer, already idempotent. **DONE.** |
|   2   | `mandates`         | MED    | One JSON file → table. Manager is well-isolated.          |
|   3   | `council_sessions` | MED    | Stuck-DEBATING bug is the use case. Two-table split.      |
|   4   | `events.ndjson`    | MED    | Big append store, multiple producers. Worth the index.    |
|   5   | `units_index`      | HIGH   | Touches the highest-traffic subsystem. Index-first,       |
|       |                    |        | not a full migration. Full units stay in JSONL + Chroma.  |

Migration pattern for each store (proven on `cost_ledger`):

1. **Build the schema.** Drop SQL file in `schema/`.
2. **Build the one-shot importer.** `scripts/migrate_<store>_to_sqlite.py`,
   idempotent on rerun via a UNIQUE constraint.
3. **Add a double-write feature flag.** Defaults OFF. Existing JSONL/JSON
   write stays untouched. SQLite failure never blocks the original write.
4. **Enable double-write in production.** Let it run for ~1 week.
5. **Verify row counts + sums match** between SQLite and the original
   store (`query_today_by_source_sqlite()` is the template).
6. **Flip the read path.** Routes start reading from SQLite.
7. **Retire the original.** JSONL can be archived.

---

## Operational notes

- **WAL recovery**: a `*.db-wal` and `*.db-shm` file sit next to `ncl.db`
  during writes. They're checkpointed back into the main DB on close or
  every ~1000 pages. Don't delete them out from under a running process.
- **Backup**: `sqlite3 ncl.db ".backup ncl.db.bak"` is the safe path
  while the Brain is running. A simple `cp` works when the Brain is down.
- **Inspection**: `sqlite3 ~/dev/NCL/data/persistence/ncl.db` opens a
  REPL. `.tables`, `.schema cost_ledger`, then run any SQL.
- **Env knobs**:
  - `NCL_SQLITE_PATH` — override DB location.
  - `NCL_COST_LEDGER_SQLITE=true` — enable cost-ledger double-write
    (default OFF — flip after a manual run of
    `scripts/migrate_cost_ledger_to_sqlite.py`).

---

## How to run the cost-ledger backfill

```bash
# Dry run — scans, parses, but writes nothing.
python3 scripts/migrate_cost_ledger_to_sqlite.py --dry-run

# Live import — idempotent, safe to rerun.
python3 scripts/migrate_cost_ledger_to_sqlite.py

# Then enable double-write so new costs land in both stores.
echo 'NCL_COST_LEDGER_SQLITE=true' >> ~/dev/NCL/.env
launchctl kickstart -k gui/$UID/com.resonanceenergy.ncl-brain
```

To verify the SQLite mirror matches the JSONL after a week:

```python
from runtime.cost_tracker import get_tracker
import asyncio
t = asyncio.run(get_tracker())
print(asyncio.run(t.query_today_by_source_sqlite()))
print(asyncio.run(t.get_daily_summary()))
```

The two should agree on per-source `calls` and `spent_usd` to the cent.
