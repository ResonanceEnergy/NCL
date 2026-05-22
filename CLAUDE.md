# NCL (NUREALCORTEXLINK) — Brain & Think Pillar

**Codename**: NCL (NUREALCORTEXLINK)
**Pillar**: Think, research, plan, remember, decide
**Analogy**: The Brain of Resonance Energy
**Authority**: Receives directives from NATRIX (absolute) → Sets mandates for NCC/BRS/AAC
**Host**: Mac Studio M1 Ultra 64GB, Tailscale IP 100.72.223.123

---

## Identity
NCL is the canonical brain cortex of the NATRIX ecosystem. It receives pump prompts from NATRIX via Grok on iPhone, chairs councils (Claude chairs; Grok, Gemini, Perplexity, GPT as members), produces mandates, manages institutional memory, and synthesizes feedback from NCC, BRS, and AAC.

**Key Role**: NATRIX intent → research/council → doctrine → mandates for downstream pillars.

---

## Runtime System

NCL Brain API runs as a **FastAPI service on port 8800** with 176+ endpoints across 20 categories. The runtime layer is autonomous and persistent.

### Autonomous Scheduler — 31 Active Tasks (as of May 22, 2026)

The scheduler now spawns 31 tasks plus a supervisor. 14 new loops added 2026-05-22 to back the new memory subsystem (BM25 rebuild, weekly eval, Chroma GC, conflict arb, staleness re-verify, narrative threading, async writer, memory budget telemetry). AAC War Room Sync removed (folded into Night Watch). Awarebot's internal `awarebot-ytc` sub-task DISABLED — superseded by `ncl-ytc-dedicated`.

| # | Task name | Method | Cadence | Status |
|---|-----------|--------|---------|--------|
| 1 | `ncl-awarebot-agent` — 8-source scanning, 6-factor scoring, tier routing, intel briefs, predictions (internal YTC sub-task DISABLED) | `Awarebot.run()` | per-source rate limits | ACTIVE (X 402; Crypto disabled) |
| 2 | `ncl-awarebot-brief` — periodic Awarebot executive-brief synthesis | `Awarebot.brief()` | hourly | ACTIVE (warm-start fix 2026-05-22) |
| 3 | `ncl-council-auto` — Delphi-MAD debate on 3+ converging signals or 4hr review | `_council_auto_loop` | 5m poll | ACTIVE |
| 4 | `ncl-memory` — decay + prune + cluster + merge + ChromaDB reindex | `_memory_consolidation_loop` | 1hr | ACTIVE |
| 5 | `ncl-workspace` — MWP pipeline stage health | `_workspace_health_loop` | 30m | ACTIVE |
| 6 | `ncl-mandate-purge` — hygiene against state-leak | `_mandate_purge_loop` | 6hr | ACTIVE |
| 7 | `ncl-feedback-synth` — pillar reports → synthesis notes | `_feedback_synthesis_loop` | 5m | ACTIVE |
| 8 | `ncl-heartbeat` — JSONL liveness + watchdog (alerts via central dispatcher) | `_heartbeat_loop` | 60s | ACTIVE |
| 9 | `ncl-working-ctx` — 6am assembly, noon refresh, 11pm EOD | `_working_context_loop` | 3x daily | ACTIVE |
| 10 | `ncl-journal-reflection` — Sonnet 4.6 daily synthesis | `_journal_reflection_loop` | 10pm ET daily | ACTIVE |
| 11 | `ncl-night-watch` — 5-phase digital cortex maintenance + startup catchup if last run >24h | `_night_watch_loop` | 2am ET nightly | ACTIVE |
| 12 | `ncl-calendar-agent` — lunar/market/local event correlation | `CalendarAgent.run()` | per-agent | ACTIVE |
| 13 | `ncl-calendar-alerts` — push critical/high alerts (via central dispatcher) | `_calendar_alert_check_loop` | 10m | ACTIVE |
| 14 | `ncl-health-rollup` — aggregated component status → `data/health/current.json` + `/system/health/rollup` | `_health_rollup_loop` | 60s | ACTIVE |
| 15 | `ncl-cost-rollover` — explicit UTC-midnight cost ledger close + JSONL `cost_day_closed` audit | `_cost_rollover_loop` | 60s poll | ACTIVE |
| 16 | `ncl-cache-warmer` — pre-touches calendar (7d/30d) + todos + sun + working context | `_cache_warmer_loop` | 5m | ACTIVE |
| 17 | `ncl-alert-dispatch` — centralized rate-limited (1/10s) + deduped (1h per-key) ntfy queue | `_alert_dispatch_loop` | 10s tick | ACTIVE |
| 18 | `ncl-ytc-dedicated` — YouTube Council with own $3/day cap; dedup window tightened 7d→1d (was 0 reports/cycle) | `_ytc_dedicated_loop` | 1hr | ACTIVE |
| 19 | `ncl-bm25-rebuild` — BM25 keyword index rebuild for FusedRetriever | `_bm25_rebuild_loop` | 30m | ACTIVE (added 2026-05-22) |
| 20 | `ncl-memory-eval` — weekly 50 Q/A regression eval; hit@5 / MRR / recall@10; ntfy on regression | `_memory_eval_loop` | Sun 3am ET | ACTIVE (added 2026-05-22) |
| 21 | `ncl-chroma-gc` — purges orphaned ChromaDB embeddings (was carrying 3× vector bloat) | `_chroma_gc_loop` | 1hr | ACTIVE (added 2026-05-22) |
| 22 | `ncl-conflict-arb` — `contradicts` edge detection + auto-enqueue to council for arbitration | `_conflict_arb_loop` | 15m | ACTIVE (added 2026-05-22) |
| 23 | `ncl-staleness` — re-verifies high-importance facts (≥70) against current signals; demotes stale | `_staleness_loop` | 6hr | ACTIVE (added 2026-05-22) |
| 24 | `ncl-narrative-threads` — cross-session entity threading; ties related units into named narratives | `_narrative_threads_loop` | 6hr | ACTIVE (added 2026-05-22) |
| 25 | `ncl-async-writer` — fire-and-forget memory write queue (4 drainers, Sonnet 4.6 enrichment in background) | `AsyncWriter.run()` | continuous | ACTIVE (added 2026-05-22) |
| 26 | `ncl-memory-budget` — per-tier token-spend rollup + cap-exceed ntfy | `_memory_budget_loop` | 15m | ACTIVE (added 2026-05-22) |
| + | `ncl-supervisor` — monitors and restarts crashed tasks (max 3 restarts) | `_supervisor_loop` | 30s | ACTIVE (supervises itself) |

> Note: The active set above is the 26 named tasks + supervisor + 4 async-writer drainer subtasks reported individually in `/autonomous/loops` = 31 entries.

**Removed:** `_aac_sync_loop` (low-value pillar-sync memory units; functionality folded into Night Watch Phase 1).

**Dormant / not yet wired:** `X Liked Videos` (READY — needs OAuth token).

**Dead code formerly listed** (`_scanner_loop`, `_prediction_loop`, `_intel_collection_loop`, `_intel_brief_loop`, `_morning_brief_loop`, `_weekly_strategy_loop`): physically removed from scheduler.py — do not re-introduce.

### New API Endpoints (latest 2026-05-22)

| Endpoint | Purpose |
|----------|---------|
| `GET /memory/search/fused?q=...&top_k=N` | Vector + BM25 + entity-graph retrieval fused via RRF (FusedRetriever) |
| `GET /memory/by-authority?min_tier=council` | Filter recall by authority tier (NATRIX, COUNCIL, BRAIN, etc.) |
| `POST /memory/backfill-authority` | One-shot migration (already run; 9,711 units tagged) |
| `GET /memory/budget` / `/memory/budget/history` / `/memory/budget/check` | Per-tier token-spend telemetry |
| `GET /memory/async-writer/{stats,dlq,retry-dlq}` | Async writer queue stats + dead-letter inspection/retry |
| `GET /memory/pii/recent` | Recent PII redactions (audit) |
| `POST/DELETE /memory/working-context/pin` | Pin/unpin memory or signal items; accepts JSON body OR query param (iOS Intel→promote-to-memory uses body) |
| `GET /intelligence/stats` | Awarebot-backed Intel header: `signal_count`, `source_count`, `last_scan_at`, `signals_routed`, `high_critical_count` |
| `GET /focus/queries` / `GET /focus/subreddits` | iOS shape: `queries.{x,youtube,reddit}` + `subreddits.{tier_1,tier_2,tier_3}` + `_meta` |
| `POST/DELETE /focus/queries` + `/focus/subreddits` | Accept tier as bare digit `1`/`2`/`3` |
| `GET /youtube/reports/recent?limit=N` | Merged feed of recent YouTube council + YouTube reports |
| `GET /system/health/rollup` | Single-call rollup: Brain, scheduler, Awarebot, costs, councils, memory, calendar, portfolio. Persisted to `data/health/current.json` |
| `/predictions` | Each item includes cleaned `description` field |
| `/autonomous/loops` | 31 loops with correct `last_run` timestamps |
| Brief endpoint | Reads both legacy `briefs.jsonl` + new `agent_briefs.jsonl` (240 entries vs 20 prior) |

### Fixes Shipped (2026-05-21 / 2026-05-22)
- **Council auto-spawn crash**: `_council_auto_loop` was crashing every 2min for 7+ hours on `AttributeError: spawn_council`. Method wired correctly.
- **Moomoo currency + N/A coercion**: Per-account native currency now read from `trdmarket_auth`; multi-account iteration restored (7 accounts syncing vs 6); `_safe_num()` coerces `'N/A'` strings to 0.0.
- **Journal reflection**: (a) Was saving UTC date but iOS queries by ET → empty result; now uses `local_today_str()`. (b) `ReflectionEngine` had `llm_client=None` → trivial template synthesis. Now wired to **Sonnet 4.6** at startup (not Haiku).
- **Working context capacity leak**: `add_item()` had no cap → 1,100+ items/day. Hard-cap 50 with lowest-salience eviction. `mark_accessed_batch()` wired into `GET /memory/working-context`. Journal→context injection now uses real `add_item()` path.
- **Heartbeat**: Was stderr-only. Now writes daily JSONL at `data/heartbeat/heartbeat-YYYY-MM-DD.jsonl` + watchdog ntfy on >2× cadence staleness.
- **`/autonomous/loops` key-mangling**: All 31 loops now show correct `last_run` (was 7 with null mapping due to Awarebot sub-task key mismatch).
- **AAC War Room Sync REMOVED** (`_aac_sync_loop` deleted). Health folded into Night Watch Phase 1.
- **Centralized AlertDispatcher**: 5 ntfy call sites migrated from direct `requests.post(NTFY_URL...)` to `AlertDispatcher.enqueue()` (1/10s global rate limit + 1h per-key dedup).
- **awarebot-brief never firing**: 2h initial sleep was reset on every Brain restart. Replaced with adaptive 60s warm-start delay.
- **YTC dedup window**: Tightened 7d → 1d (was producing 0 reports/cycle).
- **`BRAIN_AUTH_TOKEN` env**: Falls back to `STRIKE_AUTH_TOKEN` when unset (was silently failing auth).
- **`importance_scorer` + `entity_extractor`**: Accept `model=` kwarg; default Sonnet 4.6 (was Haiku — caused undersized scoring on rich text).
- **Night Watch had never fired ever**: Startup catchup added — fires immediately if last run >24h ago, then resumes 2am ET cadence.
- **Brief endpoint dual-source**: Reads both `briefs.jsonl` + `agent_briefs.jsonl` (now returns 240 entries vs 20).

### KNOWN ISSUES (as of May 20, 2026)

| Issue | Impact | Fix needed |
|-------|--------|-----------|
| **X/Twitter DISABLED** | Scanner ON HOLD per NATRIX (May 19). API 402 + cost overrun ($25-36/day). Set `X_SCANNER_ENABLED=true` in .env to re-enable. | Renew subscription + re-enable when ready |
| **Paperclip not deployed** | Only a stub exists. Full adapter wired into Brain/Council/CostGate (~500 lines) but backend never existed. **MITIGATED**: `runtime/cost_tracker.py` now handles all cost tracking with file-backed JSONL ledger + daily budgets. | Paperclip is effectively dead code; cost tracking is handled by cost_tracker.py |
| **BRS Dashboard is a stub** | `start-all.sh` runs an inline Python stub returning `{'workers': 0}`. Not a real service. | Build real BRS Dashboard or remove the stub |
| **CoinGecko rate limiting** | Crypto source disabled in Awarebot scan_cycle due to 60s+ delays from CoinGecko rate limits. | Find alternative crypto data source or upgrade CoinGecko tier |

### Background — Earlier Hardening (May 19-21, 2026)
Brief summary of pre-2026-05-22 work, kept for context. Detailed change list lives in git history.
- **Night Watch agent**: 5-phase overnight cycle (health audit, memory cycle, intel correlation, mini-councils, Sonnet synthesis). $0.88/night typical. 4,500+ lines in scheduler.py.
- **Cost tracking**: `record_cost()` wired to 20+ LLM call sites. ntfy alerting on budget warnings (80%) + caps (100%) + supervisor restart-exhaustion.
- **Supervisor self-healing**: `_supervisor_loop()` monitors all tasks, auto-restarts up to 3×.
- **SnapTrade options**: `options.list_option_holdings` per account; options show display symbols + correct market values.
- **Awarebot single-scorer**: `unified_scorer.py` retired. 6-factor composite. Tier routing in-Awarebot.
- **Sources re-enabled**: Google Trends, Polymarket, News, Unusual Whales — all through Awarebot.
- **Awarebot warm-start**: Reloads last 48h of signals from JSONL on startup.
- **Memory plumbing**: Auth fixed (`_verify_strike_token()`), ChromaDB ghost entries fixed, `$AAPL` regex added, reflection conflict detection rewritten, `get_stats()` uses actual `memory_type`/`by_type`/`by_tier`.
- **Working context**: Hybrid relevance (60% vector + 40% keyword); mid-day refresh preserves access tracking.
- **Source report cap**: `generate_source_report()` was `ranked[:5]` → now `ranked[:20]`.

### Scoring System — Single Scorer (Awarebot)

Awarebot scores every signal on ingest using a 6-factor composite (0.0-1.0 scale):

| Factor | Weight | Source |
|--------|--------|--------|
| Context Relevance | 30% | BM25 against watch queries + mandate/working-context keyword matching |
| Freshness | 20% | HN-gravity decay |
| Cross-Source | 15% | Token overlap confirmation from other sources (0/1/2/3+ confirming) |
| Source Confidence | 15% | Baseline authority + engagement + scanner-provided confidence |
| Actionability | 10% | Direction, % change, confidence, tags, URL |
| Novelty | 10% | SimHash near-dupe detection + exponential decay |

### Tier Routing (Awarebot internal, single-pass exclusive)

| Tier | Threshold | Age | Max | Description |
|------|-----------|-----|-----|-------------|
| **Focused** (green) | ≥ 0.75 | < 4h | 10 | Act now — sorted by cross-source then score |
| **Micro** (orange) | ≥ 0.50 | < 24h | 10 | Trending today |
| **Macro** (blue) | ≥ 0.30 | > 24h or narrative source | 10 | Persistent narratives |

Signals claimed exclusively (highest tier wins). API endpoints call `awarebot.route_to_tiers()` directly — no re-scoring on request.

### Active Intelligence Sources
| Source | Method | Status |
|--------|--------|--------|
| **Reddit** | RSS pre-scan + API (55 subreddits in 3 tiers) | WORKING — ~147+ signals per cycle |
| **YouTube** | yt-dlp channel scanning + per-video council reports | WORKING |
| **X/Twitter** | API v2 search | BROKEN — 402 Payment Required (circuit breaker active) |
| **X Liked Videos** | OAuth 2.0 + yt-dlp + Whisper transcription | READY — needs OAuth setup + X credits |
| **Google Trends** | pytrends | ACTIVE (re-enabled May 20) |
| **Polymarket** | Public REST API | ACTIVE (re-enabled May 20) |
| **News** | NewsAPI/GNews/RSS | ACTIVE (re-enabled May 20) |
| **Crypto** | CoinGecko free tier | DISABLED — rate limiting causes 60s+ delays |
| **Options Flow** | Unusual Whales API | ACTIVE (re-enabled May 20) — runs if API key set |

### YouTube Council — Per-Video Reports (added May 19, 2026)
YTC now produces one deep-dive report per video (full 150K char transcript budget each) plus a cross-video rollup. Reports stored in `intelligence-scan/council-reports/` and `intelligence-scan/youtube-reports/`, each ingested into ChromaDB and memory separately.

### X Liked-Video Pipeline (added May 19, 2026)
Tracks NATRIX's liked videos on X via OAuth 2.0 user auth, downloads via yt-dlp, transcribes with Whisper, analyzes per-video, stores reports + transcripts in long-term memory. Autonomous scan every 6h when OAuth token is available. Setup: set `X_OAUTH_CLIENT_ID`/`X_OAUTH_CLIENT_SECRET` in `.env`, call `POST /x/oauth/authorize`.

### Memory System (Hardened May 22, 2026)
**MemoryStore**: 10K unit capacity, ~9,711 units currently (all stamped with authority tier post-backfill). Seven-layer architecture inspired by MemGPT/Letta + Mem0, plus Zep/Graphiti-style bi-temporal KG edges.

**Core Features:**
- Two-speed decay (FadeMem): LML 0.999/day (facts, decisions, preferences, procedures), SML 0.95/day (signals, episodes)
- 6 typed ChromaDB collections + legacy default; auto-reindex after consolidation
- LLM importance scoring + entity extraction default to **Sonnet 4.6** (was Haiku)
- Knowledge graph: NetworkX DiGraph + JSONL persistence
- Reflection loop (ACE): quality, fingerprint dedup, conflict detection
- Working Context: hybrid relevance (60% vector + 40% keyword), salience now baked with **authority tier**, capacity capped at 50

**Authority Tiers (new 2026-05-22)** — every unit stamped with provenance weight; baked into salience formula in `working_context.py` and FusedRetriever rank weighting in `fusion.py`. NATRIX directives now beat scanner noise.

| Tier | Weight | Source |
|------|--------|--------|
| NATRIX | 100 | Direct user directives |
| COUNCIL | 80 | Council deliberation output |
| BRAIN | 60 | Brain-synthesized reflections / briefs |
| CALENDAR | 50 | Calendar/event-derived facts |
| LLM_SINGLE | 40 | Single-model LLM output |
| SCANNER | 20 | Awarebot scanner signals |
| RAW | 10 | Unscored ingest |

**New Memory Subsystem Modules (`runtime/memory/`)** — added 2026-05-22:
- `async_writer.py` — fire-and-forget memory write queue (4 drainers, Sonnet 4.6 enrichment in background)
- `chat_context.py` — chat amnesia fix; builds context block injected into `/chat`
- `chroma_gc.py` — orphaned-embedding purger
- `conflict_resolver.py` — `contradicts` edge detection → council arbitration queue
- `staleness_detector.py` — re-verifies high-importance facts against current signals
- `narrative_threads.py` — cross-session entity threading
- `pii_redactor.py` — on-write PII scrubber, 10 patterns, Tailscale-IP allowlist
- `procedural.py` — Night Watch Phase 2.6 skill distillation
- `temporal.py` — bi-temporal KG edges (Zep/Graphiti pattern)
- `authority.py` — 7-tier provenance system
- `budget_tracker.py` — memory context budget telemetry
- `eval/` (4 files) — weekly 50 Q/A regression harness (hit@5 / MRR / recall@10)
- `retrieval/` (3 files) — BM25 + FusedRetriever with Reciprocal Rank Fusion

**Data:** `data/memory/` (units.jsonl, chromadb/, knowledge_graph/, working_context/, bm25_index/, eval/, pii_log/)

### Journal System
Full daily journal with 9 entry types. JSONL persistence, full-text search, tag filtering. ReflectionEngine runs LLM synthesis at 10pm ET daily. Working — 2 reflections generated May 18-19. Data at `data/journal/`.

### Council System
Multi-LLM debate engine (Claude chairs; Grok, Gemini, Perplexity, GPT as members). Mandate extraction, governance pipeline, v2 runner with RAG + replay. Council outputs go to MemoryStore (not to `data/councils/` — those dirs are empty). Auto-spawn triggers on 3+ converging signals.

### Cost Tracker (added May 19, 2026) — REPLACES PAPERCLIP
Real, file-backed cost tracking with per-source daily budget enforcement. Every paid API call records to a JSONL append-only ledger (`data/costs/cost_ledger.jsonl`). Daily summaries survive restarts via replay.

**Budget Caps (daily, USD) — Platform cap: $20/day total:**
| Source | Daily Cap | Override Env Var |
|--------|----------|-----------------|
| x_twitter | $2.00 | NCL_BUDGET_X_TWITTER |
| anthropic | $2.00 | NCL_BUDGET_ANTHROPIC |
| xai | $2.00 | NCL_BUDGET_XAI |
| openai | $2.00 | NCL_BUDGET_OPENAI |
| google | $2.00 | NCL_BUDGET_GOOGLE |

**Enforcement**: Budget check runs before every paid API call. 80% warning logged, 100% hard stop blocks the call + push notification sent (via ntfy/Pushover). Platform-wide $20/day hard cap. Date rollover at midnight UTC resets totals.

**Instrumented callers**: Scanner (X tweets), YouTube analyzer (Anthropic/xAI), Brain council (Claude/Grok/Gemini), Council orchestrator (Claude/Grok), Council runner agents (Claude/Grok).

**API endpoints**: `GET /system/costs` (today's summary), `GET /system/costs/today` (detailed), `GET /system/costs/history` (30-day), `GET /system/costs/ledger` (raw entries), `POST /system/costs/record` (manual entry).

**X scan interval**: Reduced from 5min to 30min (was burning $25-36/day via 2,304 calls/day).

### Paperclip — DESIGNED BUT NOT DEPLOYED (SUPERSEDED)
Paperclip was designed as the agent orchestration backbone but no real backend was ever deployed. Cost tracking is now handled by `runtime/cost_tracker.py` instead. The Paperclip adapter (`runtime/paperclip_adapter/client.py`) still exists but is effectively dead code — CostGate in `runtime/swarm/cost_gate.py` falls back to in-memory when Paperclip is unreachable.

---

## Infrastructure

### Services (Mac LaunchAgents)
| Plist | Process | Port | Lifecycle |
|-------|---------|------|-----------|
| `com.resonanceenergy.ncl-brain.plist` | Brain API | 8800 | KeepAlive, RunAtLoad |
| `com.resonanceenergy.relay.plist` | Relay pump endpoint | 8787 | RunAtLoad |
| `com.resonanceenergy.ncl-orchestrator.plist` | Strike Point orchestrator | — | RunAtLoad |
| `com.resonanceenergy.ncl-watcher.plist` | Pump watcher | — | RunAtLoad |
| `com.resonanceenergy.ncl-councils.plist` | Council sweep | — | Every 6h, no RunAtLoad |

### Other Services (via start-all.sh, NOT LaunchAgents)
| Service | Port | Status |
|---------|------|--------|
| NCC Relay | 8787 | Real service (redundant with LaunchAgent relay) |
| NCC Master | 8765 | Real service |
| One-Drop | 8123 | Real service |
| AAC Monitor | 8080 | Has stub fallback |
| BRS Dashboard | 8000 | **STUB** — returns static JSON |
| Paperclip | 3100 | **STUB** — returns static JSON |
| Ollama | 11434 | Local LLM |

### Key Config
- **Tailscale IP**: 100.72.223.123
- **Brain port**: 8800
- **Relay port**: 8787
- **API keys**: `~/dev/NCL/.env` (sourced by `scripts/launch-brain.sh`)
- **Python**: `/opt/homebrew/bin/python3` (NOT Xcode's python3.9)
- **FirstStrike iOS**: 72+ commands, Brain Direct + Relay dual-mode, **7 tabs** (Dashboard/Portfolio/Intel/Memory/Calendar/Journal/Settings), Dashboard = Overview + Chat + Strike Point unified
- **Physical iPhone**: `00008130-000675C822A2001C` (Nathan's iPhone)
- **Physical iPad**: `00008027-001664301E07002E` (GRIP AND RIPP HDD)
- **iPhone 16e Sim**: `9F77D8B9-90B7-49F5-A654-BF6CE34F1D60`
- **iPad Pro M5 Sim**: `CE298CEE-1125-4090-8847-116691BE501B`

### Authority Chain
```
NATRIX (absolute)
  |
NCL (directive, mandates, doctrine updates)
  |
NCC (operational execution)
BRS (tactical revenue)
AAC (tactical capital investment)
  |
Feedback (interpreted only, never raw data)
```

**Key Rule**: Only NCL updates doctrine, mandates, roadmaps, and context files. NCC/BRS/AAC never set strategy — only execute work orders.

---

## DO NOT TOUCH — Critical Rules

These rules exist because previous Claude sessions broke production by ignoring them.

### 1. Mac LaunchAgents own the service lifecycle — NOT Cowork
All NCL services run via macOS LaunchAgents. The Brain's internal autonomous scheduler handles ALL intelligence sweeps, council triggers, memory consolidation, working context, journal reflections, etc.

**NEVER create Cowork scheduled tasks that duplicate Brain scheduler functionality.**
**NEVER modify, rewrite, or "improve" LaunchAgent plist files.**
**NEVER strip API keys from plists or refactor them into wrapper scripts.**
**NEVER create new startup scripts or wrapper scripts for existing services.**

If a LaunchAgent needs fixing, diagnose the issue and make the minimal targeted fix. Do not rewrite the file.

### 2. Python environment
Use `/opt/homebrew/bin/python3` — NOT Xcode's python3.9 (missing dependencies). When installing packages: `pip3 install --break-system-packages <pkg>`.

### 3. API keys live in `~/dev/NCL/.env`
The `.env` file is sourced by `scripts/launch-brain.sh` at startup. Do not hardcode keys in plists, do not move keys between files, do not create new env sourcing mechanisms.

### 4. Do not claim things are "disabled" without verifying
If disabling a source/feature, it must be done via a config flag or by removing the call from code. Verify the change is reflected at runtime. Do not just mark a task as "completed" without testing.

### 5. Do not create stubs or mocks for missing services
If a service doesn't exist (Paperclip, BRS Dashboard), acknowledge it in documentation. Do not create fake inline stubs that pretend the service is healthy.

---

## Calendar System (added May 21, 2026)

**Backend** (`runtime/calendar/`):
- `lunar.py` — Moon phase engine (Skyfield + Meeus fallback), 8-phase energy mapping, cycle context
- `events.py` — Market events: FOMC 2026, options expiry, quad witching, VIX expiry, futures roll, Finnhub economic calendar
- `local_events.py` — Local events for 7 cities (Edmonton, Calgary, Panama City, San Salvador, Montevideo, Asuncion, Oaxaca). Holidays, Open-Meteo weather alerts, Ticketmaster events, curated JSONL
- `watchlist.py` — Correlated to-do engine pulling from moon energy, predictions, scanners, council, journal, paper trades, portfolio, calendar events
- `calendar_routes.py` — FastAPI router: 12 endpoints under `/calendar/`

**API Endpoints**:
- GET `/calendar/today` — today's moon + events + context
- GET `/calendar/week` — 7-day view with phases + events
- GET `/calendar/month` — 30-day view
- GET `/calendar/moon` — current phase + cycle context
- GET `/calendar/moon/phases` — upcoming major phases
- GET `/calendar/energy` — energy state + phase-based todos
- GET `/calendar/events` — market events with date range + category filter
- POST `/calendar/events` — add custom event
- GET `/calendar/categories` — event category metadata
- GET `/calendar/cities` — available cities list
- GET `/calendar/local/{city_id}` — local events for a city
- POST `/calendar/local/events` — add curated local event
- GET `/calendar/watchlist` — full correlated to-do list

## Watch Queries (updated May 17, 2026)
- **X**: AI automation, algo trading, prediction markets, indie game dev, DUBFORGE, Claude, crypto regime, AI startup (8 queries — all failing due to 402)
- **YouTube**: AI business, crypto trading, indie game dev, AI dev tools, prediction markets, AI music (6 queries)
- **Reddit**: 6 search queries + 55 subreddits across 3 tiers (T1: 10, T2: 16, T3: 29)

---

## Routing Table

| Task Type | Trigger | Output |
|-----------|---------|--------|
| New pump prompt | `NATRIX` message | mandate package |
| Council run | `council` keyword | deliberation log + decision → MemoryStore |
| Research request | `research` keyword | research plan → UNI execution |
| Intelligence scan | auto (Awarebot) | signal report → SignalProcessor |
| Signal processing | auto (SignalProcessor) | routed to memory/context/push/JSONL |
| Memory recall | `recall` keyword | context brief |
| Journal entry | `journal` keyword | JSONL record + optional memory bridge |
| Journal reflection | 10pm ET cron | LLM synthesis → WorkingContext |
| Feedback processing | `feedback` keyword | mandate adjustments |
| Mandate status | `status` keyword | current state table |
