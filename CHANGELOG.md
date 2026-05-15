# Changelog

All notable changes to NCL (NUREALCORTEXLINK) are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/);
versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (Wave 2)
- `/feedback/synthesis` now creates `PENDING_APPROVAL` mandates from `mandate_adjustments` instead of silently dropping them.
- Intelligence engine: cross-batch anomaly fingerprint dedup (sha1 of `category|title`, persisted to `data/intelligence/anomaly_fingerprints.json`, bounded to 5000 entries).
- Intelligence engine: per-source confidence floors (polymarket ≥ 0.92, reddit ≥ 0.90, x ≥ 0.88, default ≥ 0.85).
- Intelligence engine: `intelligence-scan/snapshots/` ensured at startup.

### Fixed (Critical)
- `MandateStatus.FAILED` enum added; `_mark_dispatch_failed` no longer leaves mandates stuck in ACTIVE after NCC dispatch failure.
- `POST /mandates` now defaults to `PENDING_APPROVAL`; setting `ACTIVE` requires explicit `force=true` and is audit-logged.
- `POST /mandates/{id}/approve` routed through PolicyKernel + EmergencyStop checks instead of bypassing them.
- `_policy_allows_dispatch` now **fails closed** on every exception (was fail-open).
- `EmergencyStop.register_subsystems()` and `PolicyKernel.register_emergency_stop()` wired at lifespan startup.
- `KeepAlive.SuccessfulExit=false` removed from brain + watcher plists; replaced with plain `KeepAlive=true` so launchd reliably restarts services after clean exits.
- Watcher plist routed through `scripts/launch-watcher.sh` so `.env` is sourced before pump_watcher starts.
- `start-brain.command` no longer invokes non-existent `runtime.api.main`; now `exec`s uvicorn directly.
- `install-services.command` delegated to `scripts/install-plists.sh` (proper `__HOME__` substitution).
- `git-push.command` replaced clone-overlay-rsync with safe `git push origin HEAD` (interactive confirm).
- Docker: paperclip mock port `3102 → 3100`; mock `/api/health` alias added; Ollama healthcheck `/ → /api/tags`.

### Fixed (High)
- Council session history persisted to `data/council_sessions.json` and reloaded on startup; `GET /pump/review/{id}` no longer drops council payload after restart.
- `PumpPrompt.urgency` typed as `Literal["low","normal","high","critical"]`.
- Public `Brain.get_pending_dispatches()` accessor; routes no longer reach into private `_pending_dispatches`.
- Ollama host normalization ported from `youtube/analyzer.py` to `xai/analyzer.py`, `lde/agents.py`, `awarebot/predictor.py`, `intelligence/engine.py`.
- Predictor model IDs env-overridable (`NCL_PREDICTOR_REASONING_MODEL`, `NCL_PREDICTOR_CODE_MODEL`, `NCL_PREDICTOR_SUMMARY_MODEL`); intelligence engine summary model via `NCL_INTEL_SUMMARY_MODEL`.
- `pyproject.toml` migrated to PEP 621 deps; pins synced to `requirements.txt`; heavy `[vector]` and `[councils]` extras moved out of base requirements.
- `--break-system-packages` removed from launcher scripts (use venv).

### Added
- `scripts/launch-watcher.sh` — env-aware watcher wrapper.
- `config/com.resonanceenergy.ncl-logrotate.plist` — weekly Sunday 04:00 log rotation.
- `CHANGELOG.md` (this file) — house-rule compliance.

## [1.0.0] - 2026-04-01
- Initial NCL Brain release: mandate generation, council orchestration, intelligence scanning, memory, feedback synthesis.
