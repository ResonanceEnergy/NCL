# Changelog

All notable changes to NUREALCORTEXLINK (NCL) are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- Phase 4–6 implementation: offline resilience, schema expansion, Docker deployment, structured logging, backup/restore, Prometheus metrics, developer guides.

---

## [4.0.0] — 2026-03-16

### Added — Phase 4: iOS & Data Pipeline

- **Offline event spool** (`ncl_agency_runtime/runtime/event_spool.py`): `EventSpool` class buffers events locally when relay is unreachable and drains automatically on reconnect. Background drain thread with configurable interval.
- **Schema expansion** (7 new types, now 60 total):
  - `ncl.focus.score` — daily composite focus score
  - `ncl.health.mindfulness` — mindfulness/meditation sessions
  - `ncl.location.home_away` — home arrival/departure transitions
  - `ncl.knowledge.capture` — atomic knowledge capture events
  - `ncl.task.completed` — task completion signals
  - `ncl.mood.check_in` — mood/energy/stress check-ins (1–10)
  - `ncl.social.interaction` — social interaction metadata
- **Shortcuts Pack v2** (`shortcuts_pack/v2/`): 20 shortcuts (was 10) adding workout, sleep, mood, focus score, mindfulness, home/away, knowledge capture, task completed, and social interaction. Includes `emulate_shortcut.py` for development.

### Changed — Relay server

- Relay server hardening already complete in previous cycle: TLS (–tls-cert/–tls-key), Bearer token + X-API-Key auth, token-bucket rate limiting (60 events/min + 30 API calls/min), 1 MiB request size limit, batch endpoint (`/event/batch`).

---

## [3.5.0] — 2026-03-09

### Added — Phase 5: Deployment & Operations

- **Dockerfile**: multi-stage build (deps + runtime), non-root user (`ncl:1001`), HEALTHCHECK on `/health`.
- **Docker Compose** (`docker-compose.yml`): relay + mission runner + autonomous daemon, shared `ncl_data` volume, health-check dependency chain.
- **Backup & restore** (`tools/backup_restore.py`): hot SQLite backup via `sqlite3.backup()`, NDJSON event log archival, rotation with `--keep N`.
- **Prometheus metrics** endpoint (`/metrics`) in relay server — counters for events received/stored/quarantined/duplicates, rate_limited, and auth failures. Optional `prometheus_client` dependency; falls back to plain text if unavailable.
- **Config env-var overrides**: `load_config()` now reads `NCL_RELAY_PORT`, `NCL_EVENT_LOG_DIR`, `NCL_QUARANTINE_DIR`, `NCL_API_KEYS_REQUIRED`, `NCL_EVENTS_PER_MINUTE`, `NCL_API_CALLS_PER_MINUTE`.
- **Structured logging throughout**: replaced `print("Warning: …")` with `logger.warning(…)` in relay server, learning engine, memory API, mission runner, and `ncl_memory.py` consolidation worker.

---

## [3.4.0] — 2026-03-02 — "find and fill 1000 gaps" sweep

### Changed — Code quality

- 956 ruff violations eliminated (927 auto-fixed + 29 manual): RUF012 ClassVar annotations, F401 noqa for optional imports, B007 loop variable prefixes, E741 ambiguous names, S112 bare-continue, E402 sys-path imports.
- All 1706 tests passing (0 ruff violations, 0 mypy errors on core modules).

---

## [3.3.0] — 2026-02-28

### Added — Background services

- Matrix Monitor 30s continuous background refresh collector.
- Windows startup task registration (NCL_AutonomousDaemon, NCL_RelayServer, NCL_YouTubeDigest).
- Matrix Monitor: 54 checks across 5 source categories.

---

## [3.2.0] — 2026-02-19

### Added — Phase 3: Agent System Hardening (completed)

- `LLMBackend` abstract base, `LLMRateLimiter` (token-bucket, cost cap), `LLMManager`.
- 63-test `test_agent_hardening.py` suite covering all 8 skills.
- `MissionStatus` (lifecycle + dead-letter), `run_with_retry()` (exponential backoff), `route_mission()`.
- `PolicyGate` expanded to 6-step chain: kill-switch → system mode → provenance → consent → risk-tier → allow-list. 20 adversarial tests.
- EventBus optional NDJSON persistence + replay from disk.

---

## [3.1.0] — 2026-01-31

### Added — Phase 2: Memory System Maturation (completed)

- Consolidation pipeline: working → short-term → long-term with time-based decay.
- Search quality benchmarks (precision/recall, 1200 MemoryUnit items).
- Import/export roundtrip, anonymisation (P0/P1/P3 privacy levels).
- Concurrency stress tests (8+ threads, WAL mode + 30s busy_timeout).
- Memory analytics dashboard (`get_memory_stats()`).
- Learning engine validation (28-event synthesised week).

---

## [3.0.0] — 2025-12-01

### Added — Phase 0 & 1 baseline

- GitHub Actions CI pipeline (pytest + ruff + mypy).
- 215 → 606 tests. Coverage 54% → 86%.
- 50 golden tasks (all 8 agent skills + 5 edge cases).
- Performance benchmarks (`test_benchmarks.py`).
- All ruff violations resolved.
- 8 mypy errors on core modules resolved.

---

[Unreleased]: https://github.com/ResonanceEnergy/NCL/compare/v4.0.0...HEAD
[4.0.0]: https://github.com/ResonanceEnergy/NCL/compare/v3.5.0...v4.0.0
[3.5.0]: https://github.com/ResonanceEnergy/NCL/compare/v3.4.0...v3.5.0
[3.4.0]: https://github.com/ResonanceEnergy/NCL/compare/v3.3.0...v3.4.0
[3.3.0]: https://github.com/ResonanceEnergy/NCL/compare/v3.2.0...v3.3.0
[3.2.0]: https://github.com/ResonanceEnergy/NCL/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/ResonanceEnergy/NCL/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/ResonanceEnergy/NCL/releases/tag/v3.0.0
