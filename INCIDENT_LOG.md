# NCL Incident Log

Chronological record of production incidents in the NCL pillar (brain, watcher,
relay, council, scheduler). One entry per incident with: trigger, blast radius,
root cause, remediation, and follow-ups.

Format: most recent first.

---

## 2026-05-14 — Strike-point pipeline silent failure + duplicate-pump skip

**Severity**: P1 (data path broken; no user-facing alarm)
**Duration**: ~hours (intermittent), surfaced during iOS deploy testing
**Detected by**: Manual E2E test from `curl → relay → watcher → brain` after
installing FirstStrike on iPhone + iPad.

### Trigger
User asked to "put first strike on iphone and ipad so we can test." Building
and installing the iOS client surfaced three interlocking defects in the
pump-ingestion path.

### Blast radius
- All pumps from external clients (iPhone, dashboard, curl) failed to produce
  mandates during the affected window.
- Pump files accumulated in `mandate-generation/input/` and were never moved
  to `processed/` because the watcher's HTTP call ReadTimeout'd in a 5-second
  retry loop.
- iOS pumps would have silently landed in the stale `~/Projects/NCL` repo
  instead of the active `~/dev/NCL` repo.

### Root causes (three, stacked)

1. **Relay wrote to the wrong NCL repo.** `relay-pump-endpoint.py` hardcoded
   `NCL_INPUT_DIR = ~/Projects/NCL/mandate-generation/input/` — a snapshot
   that was last touched 30 Apr. The active brain reads from
   `~/dev/NCL/mandate-generation/input/`. Two NCL repos coexist on disk; only
   one is live.
2. **Watcher timed out before the brain finished council.** `pump_watcher.py`
   POSTed `/pump?auto_flow=true` with a 30 s `httpx.AsyncClient` timeout. The
   council pipeline takes 2–5 min in degraded mode (no Anthropic/xAI/Google
   keys → Ollama fallback for every member, every round). Result: watcher
   ReadTimeout, file never moved out of `input/`, watcher re-pumped on next
   tick → 6× brain spam per file.
3. **Watcher dedup keyed on filename only.** When `input/` was empty the
   relay's `get_next_pump_filename()` reset its NNN counter to 001, producing
   `pump-YYYYMMDD-001.json` again. The watcher's in-memory `_processed_files`
   set still contained that name from a prior tick, so the new pump was
   silently skipped — no log line, no error, no mandate.

### Remediation (commits)

| Repo | Commit | Change |
|---|---|---|
| FirstStrike | `851d373` | `relay-pump-endpoint.py` honors `NCL_INPUT_DIR` env. Plist sets it to `/Users/natrix/dev/NCL/mandate-generation/input`. |
| FirstStrike | (this session) | `get_next_pump_filename()` computes max NNN across `input/` + `processed/` + `failed/` for the day — no more recycled slots. |
| NCL | `5020bc0` | `/pump?auto_flow=true` now schedules council as `asyncio.create_task` and returns `{mode:"background", status:"accepted"}` in <100ms. Task done-callback logs any exception. Watcher timeout bumped 30 s → 180 s as defense-in-depth. |
| NCL | (this session) | `runtime/strike_point_orchestrator.py` switched hardcoded `Path.home() / "Projects" / *` to env vars (`NCL_NCC_BASE`, `NCL_AAC_BASE`, `NCL_BRS_BASE`, `NCL_FIRST_STRIKE_BASE`). |

### Verification
- `curl → relay → watcher → brain` round-trip drops from 3+ minutes (timing
  out) to ~100 ms for the HTTP layer; mandate appears in `/health` within
  ~10 s as the background council finishes.
- `tests/test_routes_smoke.py` codifies the `/pump` background-mode contract:
  10 tests covering health, services, network info, auth boundary, and the
  background vs synchronous envelopes.

### Follow-ups
- [ ] Add per-day file-content-hash (or full ISO timestamp) to relay filename
      so collisions cannot recur if `_processed_files` is keyed by name in
      future regressions.
- [ ] Wire structured stderr logging into the watcher (it already uses
      `logging`, but ReadTimeout was logged at ERROR with empty message —
      include the URL and elapsed seconds).
- [ ] Decommission `~/Projects/NCL`: archive then delete. Maintain a single
      canonical NCL repo at `~/dev/NCL`.
- [ ] Configure at least one paid LLM key (Anthropic / xAI / Google) so the
      degraded Ollama-only path is not the steady state for council runs.

---

## 2026-05-14 — Mandate / autonomous-scheduler observability gap (precursor)

**Severity**: P2 (functional success, zero observability)
**Detected by**: User asked "why don't I see scheduler logs?"

### Trigger
`AutonomousScheduler._feedback_synthesis_loop` ran, but no INFO/WARN entries
ever reached `logs/ncl-brain-stderr.log`. Same for every other `ncl.*` logger
during lifespan startup.

### Root cause
`runtime.api.routes` is the launchd entrypoint via
`python -m runtime.api.routes`. Uvicorn only configures its own `uvicorn.*`
loggers; the root logger inherited Python's default WARNING level, so every
`log.info(...)` from `ncl.autonomous`, `ncl.council`, `ncl.brain`, etc. was
silently dropped — including the scheduler banner.

### Remediation
Commit `de3fe1e` — added `logging.config.dictConfig({...})` at the top of
`runtime/api/routes.py`, BEFORE any FastAPI / scheduler import, binding a
stderr `StreamHandler` at INFO to root. Honors `NCL_LOG_LEVEL` env override.

In the same commit, `scheduler.py` was hardened:
- Every loop logs a loud entry banner before warmup.
- All imports and path resolution inside loops are wrapped in try/except
  with `log.exception`.
- `start()` attaches a `task.add_done_callback` to every spawned task; a
  silent crash now logs `[SCHEDULER] task '<name>' DIED: <type>: <repr>`.
- Hourly idle heartbeat from the synthesis loop so "alive but bored" is
  distinguishable from "dead."

### Verification
After restart, full lifecycle of the synthesis loop visible in stderr.

### Follow-ups
- [x] Documented in `/memories/repo/ncl-architecture.md`.
- [ ] Add an availability probe that asserts the scheduler loops are
      ticking (last-tick timestamp delta < 2× expected interval).
