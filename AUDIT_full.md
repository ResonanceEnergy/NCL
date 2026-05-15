# NCL Full-System Audit — 2026-05-15

Scope: every subsystem under `/Users/natrix/dev/NCL`. Cross-references prior `AUDIT_brain.md` (status verified per-finding); extends with intelligence/councils, memory/mandate/feedback lifecycle, and ops/devops surface.

Severity: **🔴 CRITICAL** | **🟠 HIGH** | **🟡 MEDIUM** | **🟢 LOW**

---

## 0. Health Snapshot (live, this run)

- Brain `/health`: ✅ healthy, paperclip_connected=true, 47 active mandates, 28 pending approval, 624 memory units
- Paperclip: ✅ live on `:3100` via OrbStack/Docker
- Watcher launchd: registered, **no PID** (launchd `KeepAlive.SuccessfulExit=false` may have dropped it on a clean exit)
- Brain launchd: registered, no PID — **brain is running but as a foreground process**, not via launchd
- Orchestrator launchd: ✅ PID 20272 running
- Councils launchd: registered, cron-style 6h trigger
- `intelligence-scan/snapshots/`: **does not exist** → no successful `run_both()` since pre-brief snapshot code landed
- YouTube council reports: **zero** (default channels 404)

---

## 1. Brain / API / Council — `AUDIT_brain.md` Status (2026-05-15)

11 of 15 prior findings FIXED. Open items:

| # | Finding | Status | Evidence |
|---|---|---|---|
| 4 | Direct `mandate.status =` bypasses state machine | **Partial** | One residual at [brain.py#L1155](runtime/ncl_brain/brain.py#L1155) (intentional fallback, but bypasses audit trail) |
| 7 | `PumpPrompt.urgency` still free-form `str` | **Open** | [models.py#L266](runtime/ncl_brain/models.py#L266); typo silently routes to default priority |
| 13 | `routes.py` reaches into `brain._pending_dispatches` | **Open** | [routes.py#L624,L652,L1462](runtime/api/routes.py#L624) — lock-guarded but no public accessor |
| 15 | `POST /mandates` defaults `ACTIVE`, bypasses approval | **Open** | [routes.py#L924](runtime/api/routes.py#L924) → [brain.py#L1105](runtime/ncl_brain/brain.py#L1105) |

---

## 2. NEW Findings — Intelligence + Councils

### 🔴 CRITICAL

- **`MandateStatus.FAILED` referenced but undefined** — [brain.py#L1078](runtime/ncl_brain/brain.py#L1078) calls `transition_to(MandateStatus.FAILED)`. The enum has no `FAILED` member → `AttributeError` swallowed by surrounding `except (ValueError, AttributeError)` → mandate stays `ACTIVE` forever after NCC dispatch failure. Same root cause class as the May 14 22k-mandate corruption.
- **`POST /mandates` and `POST /mandates/{id}/approve` bypass NATRIX approval entirely** — [routes.py#L878](runtime/api/routes.py#L878), [routes.py#L1064](runtime/api/routes.py#L1064). PolicyKernel gate at [brain.py#L1136-1156](runtime/ncl_brain/brain.py#L1136-L1156) **fails open** on every exception (`allowed = True` in except branches).
- **EmergencyStop subsystem cross-registration never invoked** — `policy_kernel.register_emergency_stop()` and `emergency_stop.register_subsystems()` exist but no caller. STOP signals the global event but does **not** freeze the kernel/scheduler/swarm/intelligence engine. Steps 2–5 of the documented STOP cascade silently no-op.

### 🟠 HIGH

- **YouTube council producing zero output** — default channels 404 ([scraper.py#L26-L29](runtime/councils/youtube/scraper.py#L26-L29)). Runner logs "No recent videos found" and exits clean. No alerting. Last YT report on disk: never.
- **`xai/analyzer.py` missing Ollama host normalization** — [analyzer.py#L28](runtime/councils/xai/analyzer.py#L28) accepts `OLLAMA_HOST` as-is. The `/11434` malformed-URL outage from the YT analyzer fix was never ported. Same gap in `lde/agents.py`, `predictor.py`, `intelligence/engine.py`.
- **`xai/analyzer.py` fallback chain is name-substring routing, not a true chain** — [analyzer.py#L194-L249](runtime/councils/xai/analyzer.py#L194-L249) gates providers by checking if `"claude"` / `"grok"` is in the model name, not by trying-each-in-order on failure.
- **Council JSON output never validated** — both `youtube/analyzer.py` and `xai/analyzer.py` fall through silently to `(raw[:500], raw)` on `json.loads` failure. No schema check on `insights` shape, no retry with "respond as JSON only".
- **Two `FeedbackReport` schemas with identical name** — [ncl_brain/models.py#L407](runtime/ncl_brain/models.py#L407) vs [feedback/models.py#L16](runtime/feedback/models.py#L16). `POST /feedback` uses brain schema; `feedback/scanner.py` uses feedback schema. **Sender CLIs ([feedback-synthesis/senders/ncc_sender.py#L115](feedback-synthesis/senders/ncc_sender.py#L115)) POST payloads that won't validate against either.**
- **Predictor model-ID sweep NOT landed** — [predictor.py#L171,L174,L225](runtime/awarebot/predictor.py#L171) hardcodes `qwen3:32b`, `deepseek-coder-v2:16b`, `claude-sonnet-4-20250514` with no env override.
- **MWP outputs land in `workspaces/mandate-generation/stages/`** — but `shared/contracts/ncl-ncc-contract.md:23` documents `mandate-generation/output/active/MANDATE-*.yaml` (YAML, not JSON; different tree). NCC consumers following the contract get nothing.
- **Council session history lost on brain restart** — `council_sessions` is in-memory only (max 50, [brain.py#L259](runtime/ncl_brain/brain.py#L259)); `pending_dispatches.json` reloads but `GET /pump/review/{id}` silently drops `review["council"]` post-restart.

### 🟡 MEDIUM

- **`_write_anomalies` no cross-batch dedup** — [engine.py#L478-L485](runtime/intelligence/engine.py#L478-L485) dedupes within one batch only. Same Polymarket/sport entries written 3× today. Threshold `confidence > 0.85` floods on Polymarket "no" markets at 90%+.
- **Anomaly log has no consumer** — pure write-only artifact. No `/anomalies` API, no autonomous loop reads back, no mandate trigger on `severity: critical`. Manual schema documented in MD header (`anomaly_id: ANO-YYYYMMDD-NNN` YAML) is **not** what the auto-writer emits (flat bullet list).
- **UNI sources are LLM-hallucinations** — [gatherer.py#L124](runtime/uni/gatherer.py#L124) `_llm_research()` asks Claude/Grok/Ollama to "research" and parses output as `SourceResult`. **No real web search, no arxiv, no news API.** Grok's `search_parameters` tool not used.
- **UNI has no public API endpoint** — `_research_cortex` initialized but no `/uni/*` routes exposed. Internal-only dispatch.
- **LDE never invoked autonomously** — only `POST /lde/process`. Doctrine output not consumed by Intelligence Engine, councils, or memory consolidation. `lde/agents.py` also lacks Ollama host normalization.
- **Reddit scanner duplication** — `awarebot/scanner.py::scan_reddit` (OAuth, returns `InsightSignal`) vs `intelligence/collectors.py::RedditCollector` (public JSON, returns `SocialSignal`). Both run in different loops with different rate-limits and signal types.
- **Memory "3-phase lifecycle" is documentary only** — no `Episodic`/`Semantic`/`Reconstructive` model. `memory-processing/{long-term,working,decay}/` are unused placeholder dirs. Real storage is `data/memory/units.jsonl`.
- **Memory decay is lazy** — only re-computed on `search_units()` or `consolidate()`. A unit never queried + never consolidated keeps original importance forever. Dead-code branch: [scheduler.py#L608-L613](runtime/autonomous/scheduler.py#L608-L613) iterates `store.units` but `MemoryStore` has no `.units` attribute (`hasattr` always False).
- **Every memory read causes full JSONL rewrite** — [store.py#L438-L454](runtime/memory/store.py#L438-L454) reinforcement triggers full file rewrite. With 10k units this is real cost.
- **`/feedback/synthesis` accepts `mandate_adjustments` and discards** — [routes.py#L1226-L1278](runtime/api/routes.py#L1226-L1278) counts in response, never converts to mandates.
- **War Room directive parser brittle** — [war_room_bridge.py#L344](runtime/councils/shared/war_room_bridge.py#L344) literal substring `"Binding Directives"` / `"## 5."`. Renamed sections silently produce empty directives.
- **War Room AAC routing path hardcoded** — `Path.home() / "Projects" / "AAC-v2" / ...` ([war_room_bridge.py#L37](runtime/councils/shared/war_room_bridge.py#L37)). Same hardcoded-paths issue as `strike_point_orchestrator.py`.
- **Hardcoded `claude-sonnet-4-20250514` in `engine.py:1003`** — exec summary model not env-configurable.
- **`config/watch_topics.json` referenced but missing** — [engine.py#L387](runtime/intelligence/engine.py#L387) falls back to 6 hardcoded topics.
- **`net_premium_ticks` and `analyst_calendar` UW collectors still missing** — flagged in user request, never built.
- **No `intelligence-scan/snapshots/` dir** → council pre-brief snapshot has never run successfully (or `data/intelligence/latest_brief.json` always missing → early-return at [runner.py#L181](runtime/councils/runner.py#L181)).

### 🟢 LOW

- Several silent `pass` swallows: reddit sub failures, news topic failures, predictor outcomes parse, atexit cleanup.
- Engine log message wrong: says "exceeded 10 MB" but limits are 100/50 MB ([engine.py#L758](runtime/intelligence/engine.py#L758)).
- `_compute_confidence` arithmetic mean penalizes unanimous-but-one-weak case ([predictor.py#L407](runtime/awarebot/predictor.py#L407)).

---

## 3. NEW Findings — Memory + Mandate + Feedback Lifecycle

(Already enumerated above where Critical/High; consolidated for clarity)

- **Mandate state machine bypassed in `try/except: pass`** — pattern throughout brain.py: `try: transition_to(...) except ValueError: mandate.updated_at = now()` swallows invalid transitions silently, no audit.
- **DRAFT and SUPERSEDED states are dead** — never used in any code path.
- **No FAILED state** but referenced (CRITICAL above).
- **PolicyKernel + ActionRouter wiring asymmetric** — Router constructed at [routes.py#L201](runtime/api/routes.py#L201) but never injected onto brain; brain calls only `kernel.execute_if_allowed`.
- **No loops outside autonomous scheduler check `EMERGENCY_STOP_EVENT`** — pump_watcher, execution_loop, strike_point_orchestrator, councils/runner ignore it.
- **`pyproject.toml` `[project.dependencies]` Poetry-style** — table where PEP 621 expects array of strings. Latent build-system bug.
- **Contract drift**: `ncl-feedback-contract.md` says YAML; scanner only globs `*.json` → YAML reports silently ignored. `ncl-paperclip-contract.md` says default port 8787; reality is 3100.
- **Two synthesis pipelines coexist** — `runtime/feedback/scanner.py` (live) vs `feedback-synthesis/senders/synthesizer.py` (CLI), no shared schema.

---

## 4. NEW Findings — Ops / DevOps

### 🔴 CRITICAL

- **`start-brain.command` BROKEN** — calls non-existent `runtime.api.main`. Should be `uvicorn runtime.api.routes:app`.
- **`install-services.command` BROKEN** — copies plists with `__HOME__` placeholders without `sed` substitution. Use [scripts/install-plists.sh](scripts/install-plists.sh) instead.
- **`git-push.command` is a clone-overlay-push** — replaces remote tree wholesale with local rsync, hardcoded commit message `feat: MANDATE-2026-008 STRIKE-POINT pipeline + doctrine + roadmap` applied to every push regardless of changes. Backup branch is the only safety net.

### 🟠 HIGH

- **`KeepAlive.SuccessfulExit=false`** on brain & watcher plists — clean exit (e.g., SIGTERM from manual kill) does not relaunch. Likely cause of current "brain registered but no PID" state.
- **Watcher plist bypasses any wrapper** — [com.resonanceenergy.ncl-watcher.plist#L9-L13](com.resonanceenergy.ncl-watcher.plist#L9-L13) calls `python3 -m runtime.pump_watcher` directly. **`.env` never sourced** → API keys missing.
- **Docker port mismatch** — `docker-compose.yml` uses 3102 for paperclip mock; canonical is 3100. `paperclip_mock.py` hardcodes 3102. Health path `/api/health` (matrix) vs `/health` (mock) also mismatched.
- **`pyproject.toml` ↔ `requirements.txt` disagree on every shared pin** (fastapi, uvicorn, pydantic, httpx, openai, google-generativeai). pyproject is months stale; CI installs from requirements.txt → that's the de-facto source of truth.
- **Extras leaked into base** — chromadb, sentence-transformers, yt-dlp, faster-whisper, twscrape pinned in `requirements.txt` despite being declared as `[vector]` / `[councils]` extras in pyproject.
- **`--break-system-packages` pip flag** in [install-services.command#L48](install-services.command#L48), [restart-all.command#L25](restart-all.command#L25), [start-all.sh#L30](start-all.sh#L30), [restart-brain-intel.command#L36](restart-brain-intel.command#L36) — bypasses PEP 668; pollutes `/opt/homebrew/lib/...`. Should use `.venv`.
- **`mypy` errors ignored in CI** — `continue-on-error: true` in [.github/workflows/ci.yml#L34](.github/workflows/ci.yml#L34).
- **No CHANGELOG.md** — violates house rule.

### 🟡 MEDIUM

- **At least 4 ways to start the brain** (`run.sh`, `start-brain.sh`, `start-all.sh`, launchd plist) plus the broken `start-brain.command`. No canonical entrypoint, no Makefile/justfile.
- **`rotate-logs.sh` not scheduled anywhere** — comment suggests cron, no plist/cron entry. Logs grow unbounded (`strike-point-orchestrator.log` 4.7M live + 5.2M+5.2M rotated; `pump-watcher.log` 934K).
- **`scripts/launch-brain.sh`** is the only clean wrapper — but only the brain plist uses it. Watcher plist doesn't.
- **`start-all.sh` falls back to inline FastAPI stubs** for AAC/BRS/Paperclip ([start-all.sh#L166-L255](start-all.sh#L166-L255)) — brain sees `/health` 200 but services are empty.
- **Watcher + strike-point orchestrator + councils** NOT started by `start-all.sh` — only by their own launchd plists.
- **Test coverage gaps**: no tests for `autonomous/scheduler.py`, `strike_point_orchestrator.py` (1154 lines), `execution_loop.py`, `councils/runner.py`, `feedback/`, `lde/`, `paperclip_adapter/`, `mcp_bridge/`, `deployment/`.
- **`config/services.json:54`** ships `"tunnel_id": "your-cloudflare-tunnel-id-here"` placeholder.
- **`config/services.json:60-67`** ships `sales@bit-rage-labour.com` SMTP/IMAP topology in plaintext (no passwords, but minor info leakage).
- **`config/services.json` AAC port disagreement** — services.json says `:8500`, matrix-config says `:8080`.
- **`config/services.json` missing BRS**; `matrix-config.json` missing Ollama; both missing One-Drop (`:8123`).
- **`config/services.json._meta.updated: "2026-04-18"`** — stale by ~1 month.
- **`mlx-whisper` (Apple-Silicon native) commented out** in requirements.txt — would be a perf win.
- **`google-api-python-client` and `youtube-transcript-api` missing** despite YT pipeline referencing them.

### 🟢 LOW

- `version: '3.8'` deprecated in compose v2 (harmless).
- README.md has lingering `8787` references that misrepresent the brain port.
- Ollama healthcheck in compose hits `/` (404) instead of `/api/tags`.
- Orchestrator plist uses `~/.pyenv/shims/python3`; brain uses homebrew — inconsistent.

---

## 5. Cross-Cutting Themes

| Theme | Evidence |
|---|---|
| **Doctrine ↔ reality drift** | Contract paths (YAML/JSON, output dirs), Paperclip ports (3100 vs 3102), AAC ports (8500 vs 8080), feedback schemas |
| **Silent failure pattern** | Bare `except` swallowing audit-critical errors; `transition_to` ValueError silently bumps timestamp only; analyzer JSON parse falls through to raw text |
| **Hardcoded paths to other repos** | `~/Projects/AAC-v2/`, `~/Projects/ncc-server/`, `~/Projects/FirstStrike/`. Breaks portability. |
| **Hardcoded model IDs** | Predictor (3 models), engine exec summary, despite recent sweep |
| **One-way write-only artifacts** | Anomaly log, MWP stage outputs, council snapshots. No consumers, no feedback loops. |
| **Approval bypass paths** | Two endpoints + PolicyKernel fail-open + EmergencyStop no-op cascade |
| **Launcher zoo** | 4+ ways to start brain, 2 plist installers (one broken), no canonical entrypoint |
| **Optional-dep coherence** | pyproject extras leaked into base requirements.txt; pins disagree |

---

## 6. Top 15 Priorities (impact-ordered)

| Pri | Item | Severity | Effort |
|---|---|---|---|
| 1 | Add `MandateStatus.FAILED` (or replace ref with `CANCELLED`); audit `_mark_dispatch_failed` | 🔴 | trivial |
| 2 | Remove `POST /mandates` ACTIVE bypass — default `PENDING_APPROVAL` or require explicit `--force-active` flag with audit | 🔴 | small |
| 3 | Wire `EmergencyStop.register_subsystems()` + `PolicyKernel.register_emergency_stop()` at startup; make PolicyKernel `_policy_allows_dispatch` **fail closed** on exception | 🔴 | small |
| 4 | Fix `start-brain.command` (or delete); fix `install-services.command` (or delete) | 🔴 | trivial |
| 5 | Replace `git-push.command` clone-overlay logic with plain `git push`; remove hardcoded message | 🔴 | trivial |
| 6 | Reconcile Paperclip docker-compose port (3102 → 3100) + mock `/api/health` path | 🟠 | small |
| 7 | Reconcile `pyproject.toml` deps to PEP 621 array form, sync pins with requirements.txt; move heavy extras (chromadb, yt-dlp etc.) out of base requirements | 🟠 | medium |
| 8 | Set `KeepAlive` to plain `<true/>` on brain+watcher plists; route watcher through `scripts/launch-brain.sh`-style wrapper that sources `.env` | 🟠 | small |
| 9 | Schedule `rotate-logs.sh` via 5th launchd plist (weekly) | 🟠 | trivial |
| 10 | Port Ollama-host normalization (`_normalize_ollama_host`) from `youtube/analyzer.py` to `xai/analyzer.py`, `lde/agents.py`, `predictor.py`, `intelligence/engine.py` | 🟠 | small |
| 11 | Unify `FeedbackReport` schema (delete one of the two; migrate sender CLIs to match) | 🟠 | medium |
| 12 | Fix YouTube council channels — `config/youtube_channels.json` content + `scrape_recent_videos` failure escalation | 🟠 | small |
| 13 | Cross-batch anomaly dedup (fingerprint + last-written-timestamp); raise threshold floor for polymarket source | 🟡 | small |
| 14 | Promote `PumpPrompt.urgency` to `Literal["low","normal","high","critical"]`; same for `source` | 🟡 | trivial |
| 15 | Add tests for `autonomous/scheduler.py`, `strike_point_orchestrator.py`, `councils/runner.py`, `feedback/scanner.py`, `paperclip_adapter/client.py` | 🟡 | medium |

---

## 7. Stretch / Architectural Items

- **Real research backend for UNI** — Grok web-search tool, arxiv API, GNews — replace LLM-hallucinated "sources" with verifiable retrieval.
- **Anomaly log → mandate trigger loop** — close the open loop by making `severity: critical` anomalies auto-create PENDING_APPROVAL mandates.
- **Memory 3-phase lifecycle implementation** — either implement Episodic/Semantic/Reconstructive as real models or remove the documentation/dirs.
- **Council session persistence** — write to `data/council_sessions.json` so `GET /pump/review/{id}` survives brain restart with full context.
- **Public accessor for `_pending_dispatches`** — eliminate routes-reaching-into-private-attr pattern.
- **Canonical entrypoint** — `Makefile` or `justfile` consolidating the launcher zoo.
- **CI hardening** — multi-version matrix, `mypy` failures = errors, `pip-audit` + `bandit`, Dockerfile build job.

---

## 8. Files Created / Touched in This Session (already committed)

- `4ba0c3c` — Sweep stale `claude-*-4-6` IDs to `claude-*-4-20250514` across 19 files; fix paperclip port `8765 → 3100` in `RUNTIME_GUIDE.md` + `MANIFEST.txt`.
- Earlier this session: `f4db4a2` (watcher fix), `ff7d3fe` (YT council), `718dbce` (Tier 3 + Tier 4), `9cb0d26` (chore brain/launcher/test), `3800dee` (data: x-council reports).

---

*Generated 2026-05-15. Status snapshot reflects HEAD `4ba0c3c`. Re-run subagent verification before claiming items closed.*
