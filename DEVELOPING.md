# Developing NCL

The missing onboarding doc. CLAUDE.md is the *spec*; this is the
*workflow*. If you're touching this repo for the first time, read
CLAUDE.md first, then come back here.

---

## Quick start

```bash
git clone <repo-url> NCL
cd NCL
make setup           # creates ./venv, installs editable with [dev] extras
make test            # pytest suite (quiet mode)
make run             # uvicorn runtime.api.routes:versioned_app on :8800
```

`make setup` uses `python3 -m venv venv`. Make sure your `python3` is
the Homebrew one (`/opt/homebrew/bin/python3`), **not** Xcode's
`python3.9` — see "Common gotchas" below.

Once `make run` is up, sanity-check:

```bash
curl http://127.0.0.1:8800/health
curl http://127.0.0.1:8800/autonomous/loops
```

You should see 32 autonomous loops listed.

---

## Architecture overview

The authoritative reads, in order:

1. **`CLAUDE.md`** — the standalone-Brain spec. What NCL is, what it is
   not (no pillars, no NCC/BRS/AAC dispatch), what loops run, what
   endpoints exist, what rules you must not break.
2. **`docs/COUNCIL_ARCHITECTURE.md`** — multi-LLM council runner,
   role map, mandate extraction, council pack assembly.
3. **`docs/COUNCIL_CONTEXT_ASSEMBLER.md`** — universal context pack
   (MMR, temporal split, 40% utilization cap, MapReduce compression,
   anonymized peer review, 3-tier write-back).
4. **`docs/PERSISTENCE.md`** — SQLite foundation. Cost ledger lives
   here in double-write; mandates / council_sessions / units_index are
   designed but not migrated yet.
5. **`docs/SECRETS.md`** — `.env` layout, keychain migration script.

Then the code:

- `runtime/api/routes.py` — FastAPI app, 176+ endpoints.
- `runtime/api/routers/system.py` — extracted `/system/*` router.
- `runtime/ncl_brain/` — the Brain core (council, mandates, models).
- `runtime/memory/` — MemoryStore, FusedRetriever, async writer,
  conflict resolver, narrative threads, PII redactor.
- `runtime/council_pack/` — universal context pack assembly.
- `runtime/scheduler.py` — the 32-loop autonomous scheduler.
- `runtime/persistence/` — SqliteStore + schema files.

---

## How to add an endpoint

### Pick the router

| If your endpoint touches… | Add to                                  |
| ------------------------- | --------------------------------------- |
| `/system/*`               | `runtime/api/routers/system.py`         |
| `/calendar/*`             | `runtime/calendar/calendar_routes.py`   |
| `/portfolio/*`            | `runtime/portfolio/portfolio_routes.py` |
| `/paper/*`                | `runtime/portfolio/paper_routes.py`     |
| anything else             | `runtime/api/routes.py`                 |

New `/<area>/*` surfaces get their own `runtime/<area>/<area>_routes.py`
with an `APIRouter(prefix="/<area>", tags=["<area>"])`, mounted from
`routes.py` via `versioned_app.include_router(...)`.

### Template

```python
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/myarea", tags=["myarea"])

@router.get("/things")
async def list_things(limit: int = Query(50, ge=1, le=500)) -> dict:
    # Touch module-level globals lazily — import inside the handler to
    # avoid circular-import landmines with routes.py.
    from runtime.api import routes as _routes
    things = await _routes.brain.things.list(limit=limit)
    return {"things": things, "count": len(things)}
```

### Auth

Mutator endpoints (POST/DELETE) take `Header("x-api-token")` and
compare to `AppSettings.api_token`. Read endpoints are open. See
existing `/system/costs/record` for the pattern.

### Test it

Add a `tests/test_<area>_routes.py` that builds a `TestClient`
around `versioned_app` and exercises the new path.

---

## How to add a memory type

The set of memory types is defined in `runtime/memory/store.py`:

```python
COLLECTION_MAP = {
    "episodic": "ncl_episodic",
    "semantic": "ncl_semantic",
    ...
}
LML_MEMORY_TYPES = {"semantic", "decision", "preference", "procedural"}
SML_MEMORY_TYPES = {"episodic", "signal"}
```

To add a new type (say, `"sensor"`):

1. **Pick a decay tier.** Slow-decay (LML, ~50% in 29 days) for facts
   and beliefs; fast-decay (SML, ~50% in 14 days) for raw signals.
   Add the literal to `LML_MEMORY_TYPES` or `SML_MEMORY_TYPES`.
2. **Add a ChromaDB collection** by extending `COLLECTION_MAP`
   (`"sensor": "ncl_sensors"`). The store auto-routes embeddings on
   `index_unit()`.
3. **Update the schema-version bump.** Bump `_UNITS_SCHEMA_VERSION` in
   `store.py` so future migrators can identify pre-`"sensor"` records.
4. **Plumb the retrieval path.** `FusedRetriever`
   (`runtime/memory/retrieval/fusion.py`) auto-includes every
   collection. The BM25 index in `runtime/memory/retrieval/bm25.py`
   is type-agnostic. So in most cases there's nothing to do here —
   just verify with a quick `GET /memory/search/fused?q=...` smoke.
5. **Add an iOS source filter chip** if it should be user-visible
   (FirstStrike `MemoryTimelineView`).

---

## How to add a council member

Council membership lives in `runtime/ncl_brain/council.py`:

```python
class CouncilMember(str, Enum):
    CLAUDE = "claude"
    GROK = "grok"
    GEMINI = "gemini"
    PERPLEXITY = "perplexity"
    GPT = "gpt"
    COPILOT = "copilot"

DEFAULT_ROLE_MAP: dict[CouncilMember, CouncilRole] = {
    CouncilMember.CLAUDE: CouncilRole.CHAIR,
    CouncilMember.GROK: CouncilRole.STRATEGIST,
    ...
}
```

To add a member (say, `"deepseek"`):

1. **Add the enum value.** `CouncilMember.DEEPSEEK = "deepseek"`.
2. **Assign a default role.** Pick one of `CHAIR / STRATEGIST /
   ANALYST / RESEARCHER / CREATIVE / ENGINEER`. There must be exactly
   one CHAIR per session — keep Claude there unless you have a strong
   reason. Add to `DEFAULT_ROLE_MAP`.
3. **Write the system prompt.** Add a `DEEPSEEK_SYSTEM_PROMPT` next
   to the others — describe the role lens this member brings, in the
   same voice as `CLAUDE_SYSTEM_PROMPT` and `GROK_SYSTEM_PROMPT`.
4. **Wire the runner.** `runtime/council_pack/runners.py` calls the
   per-member LLM client. Add the client constructor + request
   formatter. Cost-tracker integration is required:
   `record_cost("deepseek", amount_usd, ...)`.
5. **Add the API key.** `~/dev/NCL/.env` →
   `DEEPSEEK_API_KEY=sk-...`. Source via `scripts/launch-brain.sh`.
6. **Add a daily budget cap.** Default $2/day, override via
   `NCL_BUDGET_DEEPSEEK=N` env var. Update `runtime/cost_tracker.py`
   `DEFAULT_DAILY_CAPS`.

---

## How to test locally without API keys

The repo runs without any cloud LLM keys present; the council loops
will degrade gracefully. Concrete patterns:

- **Ollama fallback.** Several agents (importance scorer, entity
  extractor, dedup verifier) prefer the Anthropic API but fall back
  to a local Ollama model at `http://127.0.0.1:11434`. Set
  `NCL_OLLAMA_HOST=http://127.0.0.1:11434` and pre-pull a small
  model: `ollama pull llama3.2:3b`.
- **Dummy responses.** Set `NCL_COUNCIL_DUMMY_REPLY=true`. Council
  members return canned text; useful for end-to-end pump → mandate
  flow tests without burning budget.
- **Mock patterns.** `tests/conftest.py` exposes the
  `mock_anthropic`, `mock_grok`, `mock_chroma`, `mock_async_writer`
  fixtures. Use them in any new test that exercises a code path that
  would otherwise call out. Example:
  ```python
  @pytest.mark.asyncio
  async def test_council_runs(mock_anthropic, mock_grok):
      session = await brain.spawn_council_session(topic="...")
      assert session.status == "COMPLETE"
  ```
- **Cost gate.** Tests can flip the budget cap to $0 to verify the
  pre-call gate blocks the LLM round-trip:
  `monkeypatch.setenv("NCL_BUDGET_ANTHROPIC", "0")`.

---

## Local debugging

| What                         | Where                                                |
| ---------------------------- | ---------------------------------------------------- |
| Tail brain stderr            | `make tail-log` (alias for `tail -f logs/ncl-brain-stderr.log`) |
| Brain stderr log file        | `/Users/natrix/dev/NCL/logs/ncl-brain-stderr.log`    |
| Brain stdout log file        | `/Users/natrix/dev/NCL/logs/ncl-brain-stdout.log`    |
| Health probe                 | `curl http://127.0.0.1:8800/health`                  |
| Health rollup (snap)         | `curl http://127.0.0.1:8800/system/health/rollup`    |
| Autonomous loops dashboard   | `curl http://127.0.0.1:8800/autonomous/loops`        |
| Cost summary (today)         | `curl http://127.0.0.1:8800/system/costs/today`      |
| Mandate pipeline health      | `curl http://127.0.0.1:8800/pump/health`             |
| Memory budget telemetry      | `curl http://127.0.0.1:8800/memory/budget`           |
| Restart brain (LaunchAgent)  | `make restart-brain` (kickstarts `com.resonanceenergy.ncl-brain`) |
| Smoke council pack           | `make smoke`                                         |
| Storage reconciliation       | `python3 scripts/reconcile_storage.py --source all`  |

The Brain runs as a macOS LaunchAgent
(`com.resonanceenergy.ncl-brain`). For a one-shot restart, prefer
`make restart-brain` over killing the process — LaunchAgents
auto-restart with stale env otherwise.

---

## Common gotchas

- **Python 3.12+ required.** Several modules use the
  `asyncio.TaskGroup` and `match/case` syntax. 3.11 might compile but
  is unsupported.
- **Use `/opt/homebrew/bin/python3`, NOT Xcode's `python3.9`.** The
  Xcode toolchain ships without `aiofiles`, `chromadb`,
  `pytest-asyncio`, etc. Symptoms: `ImportError: No module named
  'aiofiles'` at brain boot.
- **Install pytest-asyncio.** Not pulled in by stock `pytest`.
  `pip3 install --break-system-packages pytest-asyncio` (or in your
  venv, just `pip install`).
- **`mandate-generation/` does not exist anymore.** It was archived
  on 2026-05-23 when the strike-point pipeline merged into the
  Brain. Do not re-create it under the repo root — see
  `archive/strike-point-pre-merge/README.md`.
- **`first-strike-chat` is CALENDAR-tier, not NATRIX.** A 2026-05-22
  retag demoted chat fragments to CALENDAR(50) so they stop
  polluting NATRIX(100) retrieval. Don't reverse this in a "fix".
- **ChromaDB collection migration is one-way.** Adding a memory type
  is safe; renaming one breaks every existing embedding's collection
  link. If you really need to rename, ship a migration script in
  `scripts/`.
- **JSONL writes are atomic per-line, not per-record.** Multi-line
  JSON in `data/**.jsonl` is a bug. Use
  `runtime/memory/conflict_resolver.py:_atomic_append_jsonl` as the
  template.
- **The Brain owns the scheduler.** Do **not** create Cowork
  scheduled tasks that duplicate any of the 32 loops. See CLAUDE.md
  "DO NOT TOUCH — Critical Rules" §1.

---

## PR checklist

Before opening a PR (or merging directly on this single-author repo):

- [ ] `make lint && make test` — both clean.
- [ ] If touching `runtime/scheduler.py` or any loop, run
      `make smoke` and check `/autonomous/loops` shows the loop
      starting once.
- [ ] If you removed code, drop a README into the archive directory
      explaining what + why + revival procedure. See
      `archive/strike-point-pre-merge/README.md` for the template.
- [ ] If the architecture changed (new pillar, new memory tier, new
      transport, new LaunchAgent), **update CLAUDE.md** in the same
      commit. Out-of-sync CLAUDE.md is the #1 source of next-session
      confusion.
- [ ] If you added a new endpoint, ensure the FirstStrike iOS client
      either consumes it or has a follow-up tracked.
- [ ] If you added a paid-API call site, ensure it's wrapped in
      `record_cost()` and gated by `can_spend()`.
- [ ] If you changed a persisted shape (`MemUnit`, contradicts_index
      record, mandate row), bump the relevant schema-version constant
      and document the migration path.
