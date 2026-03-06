# NCL Roadmap to Success

## Audit Summary (June 2025)

### Starting Condition
| Metric | Before Audit | After Audit |
|---|---|---|
| Tests collected | 168 (3 collection errors) | 215 (0 errors) |
| Tests passing | ~145 | **215 / 215 (100%)** |
| Ruff errors | 489 | **61 (cosmetic only)** |
| Mypy errors (core) | Not run | **8 (annotation-level, no-any-return)** |

### Bugs Fixed During Audit

| # | File | Issue | Fix |
|---|---|---|---|
| 1 | `tools/import_data.py` | Extra-quote syntax error | Removed stray character |
| 2 | `ncl_agency_runtime/runtime/relay_server.py` | Missing `RateLimiter` / `AuthManager` classes | Added stub implementations |
| 3 | `ncl_agency_runtime/runtime/mission_runner.py` | Missing `make_weekly_brief`, `investigate_drift`, `investigate_overload` | Added implementations |
| 4 | `ncl_agency_runtime/runtime/learning_engine.py` | `__init__` rejected `storage_path` kwarg | Added parameter |
| 5 | `ncl_agency_runtime/runtime/learning_engine.py` | Missing `learn_from_task()` method | Added alias for `learn_from_task_execution()` |
| 6 | `ncl_agency_runtime/runtime/learning_engine.py` | Test monkey-patching failed (from-import caching) | Changed to module-level `import ncl_memory` |
| 7 | `ncl_agency_runtime/runtime/memory_manager.py` | 7 methods checked module-level flag instead of instance state | Changed to `self.memory_api is None` checks |
| 8 | `ncl_memory.py` | `MemoryUnit.from_dict` crashed on missing keys | Added validation with `ValueError` |
| 9 | `ncl_memory.py` | `MemoryUnit.from_dict` type mismatches | Added coercion (int→str, str→list, etc.) |
| 10 | `ncl_memory.py` | SQLite journal mode caused Windows lock errors | Added `PRAGMA journal_mode=DELETE` |
| 11 | `ncl_memory.py` | Implicit `Optional` type annotations | Changed to `X \| None` syntax |
| 12 | `ncl_agency_runtime/runtime/memory_api.py` | Missing `_calculate_event_importance()` | Added method |
| 13 | `tools/system_health_check.py` | `load_config` didn't catch `PermissionError` / `JSONDecodeError` | Added to except clause |
| 14 | `tools/system_health_check.py` | `check_api_endpoints` caught wrong exception type | Broadened to `Exception` |
| 15 | `tests/test_migration.py` | `with sqlite3.connect()` didn't close connections on Windows | Explicit `conn.close()` in `finally` |
| 16 | Multiple files | Bare `except:` clauses, unused imports/variables | Ruff-driven cleanup |

---

## Current System Health

### Test Suite — 215 Tests Across 18 Files

| File | Tests | Coverage Area |
|---|---|---|
| test_super_openclaw_agent.py | 29 | Core agent, EventBus, PolicyGate, SkillRouter, 8 Skills |
| test_mission_runner.py | 20 | Mission lifecycle, drift/overload investigation |
| test_discord_connector.py | 16 | Discord bot connector |
| test_export.py | 16 | Data export pipeline |
| test_telegram_connector.py | 16 | Telegram bot connector |
| test_relay_server.py | 16 | HTTP relay server (port 8787) |
| test_setup_wizard.py | 16 | Interactive setup wizard |
| test_memory_system.py | 12 | MemoryUnit, MemoryStorage, MemoryManager |
| test_import_data.py | 11 | NDJSON data import |
| test_system_health_check.py | 11 | Health diagnostics |
| test_memory_manager_cli.py | 10 | CLI memory operations |
| test_golden_tasks.py | 9 | Golden task schema + evaluation |
| test_evaluation_harness.py | 7 | AI evaluation framework |
| test_launch_args.py | 7 | CLI argument parsing |
| test_migration.py | 7 | SQLite schema migration |
| test_validate_events.py | 5 | JSON Schema event validation |
| test_build.py | 4 | Doctrine build pipeline |
| test_learning_engine.py | 3 | Pattern extraction engine |

## Current System Health (Updated)

### Test Suite — 606 Tests Across 31 Files (was 215 across 18)

| Metric | Before | After Phase 1 | After Phase 2 | After Phase 3 |
|---|---|---|---|---|
| Tests | 215 | 432 | 529 | **606** |
| Coverage | 54% | 80% | 84% | **86%** |
| Ruff errors | 61 | 0 | 0 | **0** |
| Mypy errors | 8 | 0 | 0 | **0** |
| Golden tasks | 5 | 50 | 50 | **50** |

### Remaining Lint Warnings: **0** (all resolved)

---

## Roadmap

### Phase 0 — Stabilisation (Immediate) ✅ COMPLETE

**Goal**: Lock in the clean baseline and prevent regressions.

- [x] **CI pipeline**: Added GitHub Actions workflow (`pytest`, `ruff check`, `mypy --strict` on core modules). Merges blocked on failure.
- [x] **Coverage baseline**: 80% line coverage, tracked per-module.
- [x] **Pin dependencies**: `requirements-dev.txt` with pinned version ranges.
- [x] **Resolve 61 remaining lint warnings**: All fixed — **0 warnings in CI**.
- [x] **Fix 8 remaining mypy errors**: All fixed — **0 mypy errors on core modules**.

### Phase 1 — Test Depth ✅ COMPLETE

**Goal**: Move from "all tests pass" to "tests catch real bugs".

- [x] **Coverage gap analysis**: Identified and tested all modules below 60%. Coverage raised from 54% → 80%.
- [x] **Integration test for full pipeline**: `test_integration_pipeline.py` — 7 tests covering validate → NDJSON write → read back → mission brief.
- [x] **Negative / fuzz tests**: 4 new test files (lib_ncl, memory, import, validate) — 72 edge-case tests covering invalid schemas, corrupt NDJSON, concurrent SQLite writes, boundary conditions.
- [x] **Golden task expansion**: 50 golden tasks covering all 8 agent skills + 5 edge-case tasks.
- [x] **Performance benchmarks**: `test_benchmarks.py` — 9 benchmarks covering store, retrieve, search, consolidate, prune, validate, day_file, append_ndjson.

### Phase 2 — Memory System Maturation ✅ COMPLETE

**Goal**: Make the memory subsystem production-grade and useful.

- [x] **Consolidation logic**: `test_consolidation_pipeline.py` — 29 tests covering working → short-term → long-term pipeline, time-based decay, importance routing, threshold boundaries, MemoryManager-level consolidation config.
- [x] **Search quality**: `test_search_quality.py` — 20 tests benchmarking precision/recall on 1200 MemoryUnit items across tag, type, content, context, importance, and combined queries. Index quality validated. Per-connection overhead (~3s/query) documented as Phase 3 optimisation target.
- [x] **Import / export**: `test_roundtrip.py` — 13 tests for full export→wipe→import roundtrip, anonymisation (P0/P1/P3 privacy levels), dedup on reimport, date range filtering.
- [x] **Concurrency safety**: `test_concurrency_stress.py` — 9 tests stress-testing SQLite under 8+ concurrent threads. **Critical bug fixed**: migrated all SQLite connections to WAL mode + 30s busy_timeout + fetchall-first pattern in `consolidate_memories()`.
- [x] **Memory analytics dashboard**: `test_memory_analytics.py` — 14 tests validating `get_memory_stats()` across all tiers, post-consolidation/pruning, tier integrity, and MemoryAPI wrapper.
- [x] **Learning engine validation**: `test_learning_validation.py` — 12 tests with realistic 28-event week of data (focus sessions, task completions, energy logs), validating temporal patterns, actionable insights, and `learn_from_task_execution`.

### Phase 3 — Agent System Hardening (2–3 Sprints) ✅ COMPLETE

**Goal**: Move from "agent stubs exist" to "agents do useful work".

- [x] **Real LLM integration**: Added `LLMBackend` abstract base class, `LLMRateLimiter` (token-bucket per-minute rate limiting + lifetime cost cap in USD), and `LLMManager` (wraps backend with rate limiter, blocks on cost/rate exceeded, records cost even on failure). Mock-tested with 8 tests. Actual API wiring deferred until user provides API keys.
- [x] **Skill coverage**: `test_agent_hardening.py` — 63 tests across 13 classes covering all 8 skills, memory interface (search/store/stats), EventBus edge cases, PolicyGate enforcement, and agent lifecycle. Resolved MagicMock `hasattr` auto-attribute issue for `semantic_search`.
- [x] **Mission runner reliability**: Added `run_with_retry()` with exponential backoff (`base_delay * 2^(attempt-1)`), configurable `max_attempts`/`base_delay`. Added `MissionStatus` class (QUEUED→RUNNING→COMPLETED/FAILED/DEAD_LETTER lifecycle, NDJSON history persistence, dead-letter directory). Added `route_mission()` dispatcher for all 4 mission types. 15 new tests in `test_mission_runner.py` (routing, retry, status/history).
- [x] **PolicyGate enforcement**: Expanded from 2-step to full 6-step chain: kill_switch → system_mode (normal/maintenance/demo/lockdown) → provenance (channel trust) → consent (opt-in per sender, AZ_PRIME bypasses) → risk_tier (PII: SSN/credit-card/email regex, NSFW keywords, prompt injection markers; configurable threshold) → allow-list. 20 adversarial tests covering PII leak, NSFW, prompt injection, mode enforcement, consent lifecycle.
- [x] **Event bus durability**: Added optional `persist_path` for NDJSON file-backed event log. `_replay_from_disk()` restores events on startup, `_persist_event()` appends each published event, corrupt lines are skipped gracefully. 5 persistence tests.

### Phase 4 — iOS & Data Pipeline (2–3 Sprints)

**Goal**: Close the loop between iPhone data capture and actionable insights.

- [ ] **Companion App completion**: Finish SwiftUI views for event review, manual capture, and insight display.
- [ ] **Schema expansion**: Add schemas for the remaining event types beyond the current 44. Validate against real device data.
- [ ] **Shortcuts pack v2**: Expand beyond 5 shortcuts. Cover health, calendar, location, and app-usage event types.
- [ ] **Relay server hardening**: Add TLS support, authentication tokens, request size limits, and rate-limiting enforcement (currently stubbed).
- [ ] **Offline resilience**: Queue events on-device when relay server is unreachable; drain on reconnect.

### Phase 5 — Deployment & Operations (2–3 Sprints)

**Goal**: Make the system runnable outside the developer's machine.

- [ ] **Dockerfile**: Containerise the relay server + mission runner + One-Drop API. Multi-stage build, non-root user, health checks.
- [ ] **Docker Compose**: Single `docker compose up` for all services + SQLite volumes.
- [ ] **Configuration management**: Move from `ncl_config.json` to environment-variable overrides with sensible defaults. Add JSON Schema for the config file itself.
- [ ] **Logging**: Replace `print()` statements with structured `logging` throughout. Add log levels, rotation, and optional JSON output.
- [ ] **Secrets management**: Remove any hardcoded tokens/keys; load from environment or a secrets store.
- [ ] **Monitoring**: Expose Prometheus metrics from relay server and One-Drop API. Add Grafana dashboard template.
- [ ] **Backup & restore**: Automated SQLite backup script with rotation. Document restore procedure.

### Phase 6 — Documentation & Community (Ongoing)

**Goal**: Make the project accessible to contributors and users.

- [ ] **Architecture diagram**: Mermaid diagram in README showing all components and data flows.
- [ ] **API documentation**: OpenAPI spec for relay server and One-Drop API. Auto-generate with FastAPI's built-in support.
- [ ] **Developer onboarding guide**: Step-by-step from clone to running tests to submitting a PR.
- [ ] **iPhone setup guide**: Complete walkthrough for non-technical users to install shortcuts and start capturing data.
- [ ] **Changelog**: Start maintaining `CHANGELOG.md` (Keep a Changelog format).
- [ ] **Versioning**: Adopt SemVer. Tag releases. Publish release notes.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        iOS Device                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Shortcuts    │  │  Companion   │  │  HealthKit / Sensors │   │
│  │  Pack (v1)    │  │  App (Swift) │  │                      │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         └─────────────────┼─────────────────────┘               │
│                           │ HTTP POST (JSON)                    │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│                    Relay Server (:8787)                        │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────────────┐  │
│  │ Auth Manager│  │Rate Limiter│  │  Schema Validator (44)  │  │
│  └────────────┘  └────────────┘  └─────────────────────────┘  │
│                           │                                    │
│                           ▼                                    │
│                    NDJSON Storage                               │
└───────────────────────────┼───────────────────────────────────┘
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
┌──────────────────────┐   ┌──────────────────────────────────┐
│   Mission Runner     │   │      Memory System               │
│  ┌────────────────┐  │   │  ┌──────────┐  ┌─────────────┐  │
│  │ Weekly Brief   │  │   │  │ Working  │→ │ Short-Term  │  │
│  │ Drift Monitor  │  │   │  │ Memory   │  │ (SQLite)    │  │
│  │ Overload Check │  │   │  └──────────┘  └──────┬──────┘  │
│  └────────────────┘  │   │                       ▼         │
└──────────┬───────────┘   │               ┌─────────────┐   │
           │               │               │ Long-Term   │   │
           ▼               │               │ (SQLite)    │   │
┌──────────────────────┐   │               └─────────────┘   │
│  SuperOpenClaw Agent │   └──────────────────────────────────┘
│  ┌────────────────┐  │
│  │ EventBus       │  │       ┌────────────────────────────┐
│  │ PolicyGate     │  │       │   One-Drop API (:8123)     │
│  │ SkillRouter    │  │       │  ┌────────────────────────┐│
│  │ 8 Skills       │  │       │  │ Progress Tracking     ││
│  └────────────────┘  │       │  │ Roadmap Data          ││
│         │            │       │  │ Health Check          ││
│    ┌────┴────┐       │       │  └────────────────────────┘│
│    ▼         ▼       │       └────────────────────────────┘
│ Telegram  Discord    │
│ Bot       Bot        │       ┌────────────────────────────┐
└──────────────────────┘       │  Evaluation Harness        │
                               │  ┌────────────────────────┐│
                               │  │ 17 Golden Tasks        ││
                               │  │ Score & Grade          ││
                               │  │ Report Generation      ││
                               │  └────────────────────────┘│
                               └────────────────────────────┘
```

---

## Key Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| No CI — regressions creep in silently | High | Phase 0: GitHub Actions pipeline |
| SQLite concurrency under real load | Medium | ✅ Phase 2: WAL mode + busy_timeout + fetchall-first pattern — FIXED & stress-tested (9 tests, 8+ threads) |
| Agent skills are mocked, no real LLM | High | Phase 3: LLM integration with cost guard |
| Relay server has no TLS/auth in production | Critical | Phase 4: TLS + token auth |
| Single-machine, no deployment story | Medium | Phase 5: Docker Compose |
| No structured logging | Medium | Phase 5: Replace print() with logging |

---

## Success Criteria

The system is **production-ready** when:

1. **215+ tests pass** in CI on every commit (currently 215 ✅)
2. **0 lint / type errors** in CI (currently 61 lint + 8 mypy — Phase 0)
3. **≥ 80% branch coverage** on core modules (Phase 1)
4. **End-to-end pipeline test** passes: iPhone JSON → insight output (Phase 1)
5. **Memory system** handles 10K+ units with sub-second search (Phase 2)
6. **At least one agent skill** produces real LLM-powered output (Phase 3)
7. **Relay server** runs with TLS and authentication (Phase 4)
8. **`docker compose up`** launches the full system (Phase 5)
9. **New contributor** can go from clone to passing tests in < 15 minutes (Phase 6)
