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

### Autonomous Scheduler — 32 Active Tasks (as of May 22, 2026 EOD)

| # | Task name | Method | Cadence | Status |
|---|-----------|--------|---------|--------|
| 1 | `ncl-awarebot-agent` — 8-source scanning, 6-factor scoring, tier routing, intel briefs, predictions (internal YTC sub-task DISABLED) | `Awarebot.run()` | per-source rate limits | ACTIVE (X 402; Crypto disabled) |
| 2 | `ncl-awarebot-brief` — periodic Awarebot executive-brief synthesis | `Awarebot.brief()` | hourly | ACTIVE |
| 3 | `ncl-council-auto` — Delphi-MAD debate on 3+ converging signals or 4hr review | `_council_auto_loop` | 5m poll | ACTIVE |
| 4 | `ncl-memory` — decay + prune + cluster + merge + ChromaDB reindex | `_memory_consolidation_loop` | 1hr | ACTIVE |
| 5 | `ncl-workspace` — MWP pipeline stage health | `_workspace_health_loop` | 30m | ACTIVE |
| 6 | `ncl-mandate-purge` — hygiene against state-leak | `_mandate_purge_loop` | 6hr | ACTIVE |
| 7 | `ncl-feedback-synth` — pillar reports → synthesis notes | `_feedback_synthesis_loop` | 5m | ACTIVE |
| 8 | `ncl-heartbeat` — JSONL liveness + watchdog (alerts via central dispatcher) | `_heartbeat_loop` | 60s | ACTIVE |
| 9 | `ncl-working-ctx` — 6am assembly, noon refresh, 11pm EOD | `_working_context_loop` | 3x daily | ACTIVE |
| 10 | `ncl-journal-reflection` — Sonnet 4 daily synthesis (`claude-sonnet-4-20250514`) | `_journal_reflection_loop` | 10pm ET daily | ACTIVE |
| 11 | `ncl-night-watch` — 5-phase maintenance (M1 is now a no-op that reads `last_dedup_scan_merged_24h`) | `_night_watch_loop` | 2am ET nightly | ACTIVE |
| 12 | `ncl-calendar-agent` — lunar/market/local event correlation | `CalendarAgent.run()` | per-agent | ACTIVE |
| 13 | `ncl-calendar-alerts` — push critical/high alerts (via central dispatcher) | `_calendar_alert_check_loop` | 10m | ACTIVE |
| 14 | `ncl-health-rollup` — aggregated component status → `data/health/current.json` + `/system/health/rollup` | `_health_rollup_loop` | 60s | ACTIVE |
| 15 | `ncl-cost-rollover` — UTC-midnight cost ledger close + JSONL `cost_day_closed` audit | `_cost_rollover_loop` | 60s poll | ACTIVE |
| 16 | `ncl-cache-warmer` — pre-touches calendar (7d/30d) + todos + sun + working context | `_cache_warmer_loop` | 5m | ACTIVE |
| 17 | `ncl-alert-dispatch` — centralized rate-limited (1/10s) + deduped (1h per-key) ntfy queue | `_alert_dispatch_loop` | 10s tick | ACTIVE |
| 18 | `ncl-ytc-dedicated` — YouTube Council with own $3/day cap; dedup window 1d | `_ytc_dedicated_loop` | 1hr | ACTIVE |
| 19 | `ncl-bm25-rebuild` — BM25 keyword index rebuild for FusedRetriever | `_bm25_rebuild_loop` | 30m | ACTIVE |
| 20 | `ncl-memory-eval` — weekly 50 Q/A regression eval; hit@5 / MRR / recall@10; ntfy on regression | `_memory_eval_loop` | Sun 3am ET | ACTIVE |
| 21 | `ncl-chroma-gc` — purges orphaned ChromaDB embeddings (zero-ghost collections now preserved in output) | `_chroma_gc_loop` | 1hr | ACTIVE |
| 22 | `ncl-conflict-arb` — `contradicts` edge detection + council arbitration; cap 50/cycle, adaptive cadence | `_conflict_arb_loop` | 5/10/15m (backlog-adaptive) | ACTIVE |
| 23 | `ncl-staleness` — re-verifies high-importance facts (≥70) using `created_at` (not `last_accessed`) | `_staleness_loop` | 6hr | ACTIVE |
| 24 | `ncl-narrative-threads` — cross-session entity threading; ties related units into named narratives | `_narrative_threads_loop` | 6hr | ACTIVE |
| 25 | `ncl-async-writer` — fire-and-forget memory write queue (4 drainers, Sonnet 4 enrichment, budget-gated) | `AsyncWriter.run()` | continuous | ACTIVE |
| 26 | `ncl-memory-budget` — per-tier token-spend rollup + cap-exceed ntfy | `_memory_budget_loop` | 15m | ACTIVE |
| 27 | `ncl-dedup-scan` — sliding-window 500-unit M1 dedup (lifted out of Night Watch after 30m timeout) | `_dedup_scan_loop` | 6hr | ACTIVE (new EOD 2026-05-22) |
| 28 | `ncl-claude-md-refresh` — re-ingests `CLAUDE.md` as procedural memory (importance 90, BRAIN tier) | `_claude_md_refresh_loop` | 24hr | ACTIVE (new EOD 2026-05-22) |
| + | `ncl-supervisor` — monitors and restarts crashed tasks (max 3 restarts) | `_supervisor_loop` | 30s | ACTIVE (supervises itself) |

> Active set: 28 named tasks + supervisor + 4 async-writer drainer subtasks (reported individually in `/autonomous/loops`) = 32 entries.

**Removed:** `_aac_sync_loop` (low-value pillar-sync memory units; functionality folded into Night Watch Phase 1).

**Dormant / not yet wired:** `X Liked Videos` (READY — needs OAuth token).

**Dead code formerly listed** (`_scanner_loop`, `_prediction_loop`, `_intel_collection_loop`, `_intel_brief_loop`, `_morning_brief_loop`, `_weekly_strategy_loop`): physically removed from scheduler.py — do not re-introduce.

### API Endpoints (current 2026-05-22 EOD)

| Endpoint | Purpose |
|----------|---------|
| `GET /memory/search/fused?q=...&top_k=N` | Vector + BM25 + entity-graph via RRF. Surfaces `tier`+`signal_id`. `NCL_FUSION_MIN_SCORE` env knob |
| `GET /memory/by-authority?min_tier=council` | Filter recall by authority tier |
| `POST /memory/backfill-authority` / `POST /memory/retag-authority` | One-shot migrations (both already run; 9,711 units re-tagged) |
| `POST /memory/bootstrap-claude-md` | Ingest CLAUDE.md files as procedural memory |
| `POST /memory/kg-cleanup` | Purge URL/domain noise nodes (one-shot) |
| `GET /memory/budget` / `/memory/budget/history` / `/memory/budget/check` | Per-tier token-spend telemetry |
| `GET /memory/async-writer/{stats,dlq,retry-dlq}` | Async writer queue stats + DLQ inspection/retry |
| `GET /memory/pii/recent` | Recent PII redactions (audit) |
| `POST/DELETE /memory/working-context/pin` | Pin/unpin items; JSON body or query param |
| `GET /system/memory-profile` | RSS / objects / buffer sizes |
| `GET /system/health/rollup` | Brain, scheduler, Awarebot, costs, councils, memory (units fixed via async-aware `get_stats()`), calendar, portfolio. Persisted to `data/health/current.json` |
| `GET /council/quality` | Auto-fixes stuck DEBATING sessions + counters |
| `GET /pump/health` | Pump pipeline health (`mandate-generation/{input,processed,failed}`) |
| `GET /intelligence/stats` | Awarebot Intel header: `signal_count`, `source_count`, `last_scan_at`, `signals_routed`, `high_critical_count` |
| `GET /focus/queries` / `GET /focus/subreddits` | iOS shape: `queries.{x,youtube,reddit}` + `subreddits.{tier_1,tier_2,tier_3}` + `_meta` |
| `POST/DELETE /focus/queries` + `/focus/subreddits` | Accept tier as bare digit `1`/`2`/`3` |
| `GET /youtube/reports/recent?limit=N` | Recent YTC + YouTube reports, dedup by `video_id` |
| `GET /predictions` | Each item: cleaned `description`, `direction` (regex classifier), `models` (parsed from `[Consensus: lead=X][Y concurs]`), `linked_signals` |
| `GET /autonomous/loops` | 32 loops with correct `last_run` |
| `GET /portfolio/accounts` | `positions_count` propagation fixed |
| `GET /portfolio/options-flow` | **NEW EOD** — top-20 grouped by ticker with premium splits + call/put ratio + `is_held_in_portfolio` flag |
| `GET /calendar/events/compiled?window=30` | Auto-excludes first 7 days; scanner contribution capped at 30% (was 93%) |

### Fixes Shipped Today (EOD swarm, commit `25c3710`)

**P0 — model + lock + crash**
- Model 17-site sweep: `claude-sonnet-4-6-20250514` → `claude-sonnet-4-20250514` (was returning HTTP 404)
- MemoryStore reader-counter lock leak: replaced ad-hoc Lock+counter+Event with `asyncio.Condition` (writer-preference, no lost-wakeups). 500 writes 16s → 0.87s
- `awarebot-x-liked` crash: `self._shutdown_event` → `self._running`
- Health rollup `memory.units=0`: `get_stats()` is an async coroutine — now properly awaited + `units.jsonl` line-count fallback
- YTC `_auto_ingest_report` migrated from sync `httpx` to `async_writer.enqueue` (was blocking 2N+1 roundtrips per session)
- Staleness selector now reads `created_at` (was `last_accessed`, bumped by working-context refresh)
- ChromaDB GC now preserves zero-ghost collections in output (was dropping them)
- M1 dedup lifted into own 6h loop (was timing out at 30min inside Night Watch on false-positive comparator)
- `MAX_TOTAL_UNITS` 10K → 25K (was thrashing eviction every ~4s)
- Anthropic daily cap $5 → $15 (was hitting cap by 18:00 ET)
- `first-strike-chat` re-tagged NATRIX(100) → CALENDAR(50) (was polluting TSLA searches)

**P0 — council + pump + KG + budget (final swarm)**
- Council runner persistence: every session since 2026-05-17 was persisting at `status=DEBATING` but never updating final state. Now force-persists. 9 stuck sessions auto-marked failed
- Pump pipeline: real path is `mandate-generation/{input,processed,failed}` (not `data/pumps/*`). Strike Point orchestrator unblocked: `httpx` install + MANDATE-2026-008 empty-pillar handling
- Bounded `contradicts_index.jsonl` at 5MB (was 30MB append-only; OOM risk)
- Calendar 3-city notable_dates backfilled (panama_city, montevideo, asuncion). Compiled events 521→19; scanner-sourced 487→45
- KG entity extractor blacklists `*.com` domains + yfinance sector buckets. Top-10 entities 100% noise (reddit.com 9774) → 100% real (Claude Code, Council Insight)
- Authority retag: NATRIX(100) units 305→3. Polluted units (`portfolio:significant_move`, chat fragments) demoted to BRAIN(60)
- CLAUDE.md ingested as procedural memory (importance 90, BRAIN tier) via new 24h refresh loop
- Async writer budget gates: every Sonnet enrichment checks `can_spend("anthropic", 0.01)` BEFORE the API. 429/529/503 → 3 retries exp backoff. 401/403/404 → DLQ + ntfy
- `create_unit` lifts Awarebot `route_level` onto `unit.tier` (focused/micro/macro), stamps `authority_tier` from source
- Portfolio quotes feed: field-name mismatch fixed (`current_price` vs `last_price`). New `quote_ok` flag. Absurd `daily_pl_pct` clamped

### KNOWN ISSUES

| Issue | Impact | Fix needed |
|-------|--------|-----------|
| **X/Twitter DISABLED** | Scanner ON HOLD per NATRIX (May 19). API 402 + cost overrun. Set `X_SCANNER_ENABLED=true` in .env to re-enable. | Renew subscription |
| **Paperclip not deployed** | Adapter wired but backend never existed. **MITIGATED** by `runtime/cost_tracker.py`. | Paperclip is dead code; cost_tracker.py owns this |
| **BRS Dashboard is a stub** | `start-all.sh` runs an inline Python stub returning `{'workers': 0}`. | Build real BRS Dashboard or remove the stub |
| **CoinGecko rate limiting** | Crypto source disabled (60s+ delays). | Alternative source or paid tier |

### Tailscale Mesh (verified GREEN EOD 2026-05-22)
All 3 peers on direct LAN — no DERP relay:
- Mac Studio: `100.72.223.123` (host)
- iPad (GRIP AND RIPP HDD): `100.76.184.123` (9ms)
- iPhone (Nathan's iPhone): `100.82.59.60` (19ms)

### Background — Earlier Hardening (May 19-22, 2026)
Brief summary of pre-EOD work, kept for context. Detailed list lives in git.
- **Night Watch agent**: 5-phase overnight cycle ($0.88/night typical). M1 dedup now offloaded to dedicated `ncl-dedup-scan` loop.
- **Cost tracking**: `record_cost()` wired to 20+ LLM call sites. ntfy on 80% / 100% / supervisor restart-exhaustion.
- **Supervisor self-healing**: `_supervisor_loop()` monitors all tasks, auto-restarts up to 3×.
- **SnapTrade options**: `options.list_option_holdings` per account.
- **Awarebot single-scorer**: 6-factor composite. Tier routing in-Awarebot. Warm-start reloads last 48h.
- **Sources re-enabled** (May 20): Google Trends, Polymarket, News, Unusual Whales.
- **Memory plumbing**: Auth fixed, ChromaDB ghosts fixed, `$AAPL` regex, `get_stats()` uses actual `memory_type`/`by_type`/`by_tier`.
- **Memory subsystem (morning 2026-05-22)**: BM25, FusedRetriever, async writer, PII redactor, narrative threads, conflict resolver, staleness detector, authority tiers, weekly eval harness, ChromaDB GC, memory budget telemetry. Centralized AlertDispatcher (1/10s rate-limit, 1h dedup). All shipped earlier today — EOD work patched their P0 bugs.

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

### Memory System (Hardened May 22, 2026 EOD)
**MemoryStore**: **25K unit capacity** (bumped from 10K — was thrashing eviction every ~4s), ~9,711 units stamped with authority tier post-retag. Seven-layer architecture inspired by MemGPT/Letta + Mem0, plus Zep/Graphiti bi-temporal KG edges.

**Core Features:**
- Two-speed decay (FadeMem): LML 0.999/day (facts, decisions, preferences, procedures), SML 0.95/day (signals, episodes)
- 6 typed ChromaDB collections + legacy default; auto-reindex after consolidation
- LLM importance scoring + entity extraction on **Sonnet 4** (model id `claude-sonnet-4-20250514`)
- Knowledge graph: NetworkX DiGraph + JSONL persistence. URL/domain noise blacklisted at extractor
- Reflection loop (ACE): quality, fingerprint dedup, conflict detection
- Working Context: hybrid relevance (60% vector + 40% keyword), salience baked with **authority tier**, capacity capped at 50
- Reader/writer concurrency now `asyncio.Condition` (writer-preference); 500 writes 16s → 0.87s
- `contradicts_index.jsonl` bounded at 5MB (was 30MB append-only)

**Authority Tiers** — every unit stamped with provenance weight; baked into salience in `working_context.py` and FusedRetriever rank weighting in `fusion.py`. Post-retag, NATRIX(100) shrunk 305→3 (polluted `portfolio:significant_move` + chat fragments demoted to BRAIN(60)).

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

**Budget Caps (daily, USD):**
| Source | Daily Cap | Override Env Var |
|--------|----------|-----------------|
| x_twitter | $2.00 | NCL_BUDGET_X_TWITTER |
| anthropic | $15.00 | NCL_BUDGET_ANTHROPIC |
| xai | $2.00 | NCL_BUDGET_XAI |
| openai | $2.00 | NCL_BUDGET_OPENAI |
| google | $2.00 | NCL_BUDGET_GOOGLE |

> Anthropic raised $5 → $15 EOD 2026-05-22 (was hitting cap by 18:00 ET after Sonnet-everywhere migration).

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
- **FirstStrike iOS**: 72+ commands, Brain Direct + Relay dual-mode, **6 bottom tabs** (Dashboard/Portfolio/Intel/Memory/Calendar/Journal) — Settings now lives behind gear icon in Dashboard header. Portfolio has 5 sub-tabs (Portfolio/GOAT/Bravo/Paper/OPTIONS), Intel has 9, Calendar has 6, Memory has 4
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
