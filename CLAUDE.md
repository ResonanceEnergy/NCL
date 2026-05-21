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

### Autonomous Scheduler — 11 Active Tasks (as of May 2026)

The Awarebot agent consolidation merged 6 former standalone loops into a single `awarebot.run()` task. The scheduler now spawns 11 tasks:

| # | Task | Cadence | Status |
|---|------|---------|--------|
| 1 | **Awarebot agent** — 8-source scanning, 6-factor scoring, tier routing, intel briefs, predictions | X: 5m, Reddit: RSS, YT: 10m, others: per-source rate limits | ACTIVE (X returns 402; Crypto disabled) |
| 2 | **Council Auto-Spawn** — triggers on 3+ converging signals or 4hr review | event-driven | ACTIVE |
| 3 | **Memory Consolidation** — decay + prune + cluster + merge | 1hr | ACTIVE |
| 4 | **AAC War Room Sync** | 15m | ACTIVE |
| 5 | **Workspace Health** | 30m | ACTIVE |
| 6 | **Mandate Purge** | 6hr | ACTIVE |
| 7 | **Feedback Synthesis** | 5m | ACTIVE |
| 8 | **Heartbeat** | 60s | ACTIVE |
| 9 | **Working Context** — 6am assembly, noon refresh, 11pm EOD | 3x daily | ACTIVE |
| 10 | **Journal Reflection** — LLM synthesis | 10pm ET daily | ACTIVE |
| 11 | **X Liked Videos** — OAuth liked-tweet scan, video download, transcribe, analyze | 6hr | READY (needs OAuth token) |

**Dead code** (methods exist in scheduler.py but NOT spawned — replaced by Awarebot):
`_scanner_loop`, `_prediction_loop`, `_intel_collection_loop`, `_intel_brief_loop`, `_morning_brief_loop`, `_weekly_strategy_loop`

### KNOWN ISSUES (as of May 20, 2026)

| Issue | Impact | Fix needed |
|-------|--------|-----------|
| **X/Twitter DISABLED** | Scanner ON HOLD per NATRIX (May 19). API 402 + cost overrun ($25-36/day). Set `X_SCANNER_ENABLED=true` in .env to re-enable. | Renew subscription + re-enable when ready |
| **Paperclip not deployed** | Only a stub exists. Full adapter wired into Brain/Council/CostGate (~500 lines) but backend never existed. **MITIGATED**: `runtime/cost_tracker.py` now handles all cost tracking with file-backed JSONL ledger + daily budgets. | Paperclip is effectively dead code; cost tracking is handled by cost_tracker.py |
| **BRS Dashboard is a stub** | `start-all.sh` runs an inline Python stub returning `{'workers': 0}`. Not a real service. | Build real BRS Dashboard or remove the stub |
| **CoinGecko rate limiting** | Crypto source disabled in Awarebot scan_cycle due to 60s+ delays from CoinGecko rate limits. | Find alternative crypto data source or upgrade CoinGecko tier |

### RESOLVED ISSUES (fixed May 19-21, 2026)
- **Night Watch autonomous agent (5-phase overnight cycle, May 21)**: Full digital cortex maintenance system running 2am-5am ET. Phase 1: Deterministic health audit (services, loops, staleness, disk, LLM connectivity, costs). Phase 2: Memory cycle (semantic dedup via ChromaDB, deep re-scoring of rule-only units, entity backfill to knowledge graph, stale fact detection, KG maintenance + pruning, entity normalization). Phase 3: Intel correlation (cross-source mining, coverage blind spots, signal score calibration, prediction calibration per-model, council topic suggestions saved to data/night-watch/, cost optimization analysis). Phase 4: Mini-council sessions (Claude+Grok 3-call debate pattern on 4 domains: memory review, intel review, portfolio risk assessment, journal strategy review). Phase 5: Sonnet synthesis compositing all findings into single daily brief pushed via ntfy. Portfolio and journal data collection integrated. Budget: $1/night ($0.88 typical). 4,500+ lines in scheduler.py.
- **Full cost tracking + alerting (May 21)**: (1) Wired `record_cost()` to all 20+ previously untracked LLM call sites (Awarebot predictions, memory scoring, entity extraction, intel summaries, Perplexity/GPT/Copilot council members, UNI research, X/Twitter analysis, war room, swarm, user chat). Added `perplexity` to budget config. (2) ntfy alerting on availability tracker alerts (regression, latency spikes, workflow down) with severity-mapped priorities. Cost tracker budget warnings (80%) and hard caps (100%) push ntfy alerts with daily rate limiting. (3) Supervisor self-healing — `_supervisor_loop()` monitors all scheduler tasks every 30s, auto-restarts crashed tasks up to 3 times, sends ntfy alert when a task exhausts restart budget.
- **Autonomous loops endpoint aligned** — `/autonomous/loops` updated from stale 4-loop list to actual 18 running tasks (7 scheduler + 8 Awarebot + supervisor + night-watch + mandate-purge/feedback-synth). Dead Cowork agents UI removed from FirstStrike SchedulerView (115 lines dead code). Build artifacts `.gitignored`.
- **SnapTrade option holdings** — Added `options.list_option_holdings` call per account in `get_positions()`. Options now show with display symbols (e.g. "GLD $515C 03/19/27"), correct market values (price * 100 * contracts), and `asset_class: "option"`.
- **Predictions now working** — Awarebot generates predictions with full side effects (memory, disk, push, council flagging). `/predictions` endpoint has 15s timeout protection.
- **X/Twitter money burn stopped** — 402 added to immediate-raise list in scanner.py. No more wasted retries.
- **Scoring consolidated** — unified_scorer.py RETIRED. Awarebot is the single scorer with 6-factor composite (context_relevance, freshness, cross_source, source_confidence, actionability, novelty). Tier routing happens in Awarebot directly.
- **Sources re-enabled** — Google Trends, Polymarket, News, Unusual Whales all flow through Awarebot pipeline now.
- **Context warm-start** — Awarebot reloads last 48h of signals from JSONL archive on startup. Tiers populate immediately instead of being empty for hours.
- **Intel/Sources separation** — iOS IntelView split into Context (Focused/Micro/Macro/Brief) and Sources (Reddit/YTC/X/Trends/Markets/News) with visual divider.
- **Memory API auth crash** — All 9 new memory endpoints used undefined `_check_auth()`. Fixed to `_verify_strike_token()`.
- **Reflection conflict detection** — Dead code in reflection.py (wrong tuple unpacking). Rewritten to properly detect importance divergence > 40 on 2+ shared tags.
- **Ticker entity extraction** — Only matched contextual format (`AAPL stock`). Now also matches `$AAPL` dollar-sign format + expanded context words.
- **ChromaDB ghost entries** — Pruned/merged units left ghost entries in vector store. Both `consolidate()` and `consolidate_v2()` now reindex after completion.
- **LLM scoring/extraction enabled** — High-value content (rule score >= 7) triggers Claude Haiku importance scoring. High-importance units (>= 70) get LLM entity extraction during consolidation.
- **get_stats() wrong proxy** — Used `reinforcement_count` as proxy for memory type. Now uses actual `memory_type` field + `by_type`/`by_tier` breakdowns.
- **Working context hybrid relevance** — Upgraded from keyword-only to 60% ChromaDB vector similarity + 40% keyword overlap.
- **Working context refresh()** — No longer discards `accessed_today`/`access_count` state during mid-day refresh.
- **Markets/Trends/News item counts** — `generate_source_report()` was capped at `ranked[:5]`. Fixed to `ranked[:20]`.

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

### Memory System (Enhanced May 20, 2026 — Full Audit)
**MemoryStore**: 10K unit capacity, ~1,801 units currently. Seven-layer architecture inspired by MemGPT/Letta and Mem0.

**Core Features:**
- Two-speed decay (FadeMem): LML 0.999/day (facts, decisions, preferences, procedures), SML 0.95/day (signals, episodes)
- Auto-tier routing: memory_type determines LML/SML assignment at write time
- 6 typed ChromaDB collections + legacy default, auto-reindexed after consolidation
- LLM importance scoring (Claude Haiku): auto-triggers for high-value content (rule score >= 7.0)
- Entity extraction: fast regex ($AAPL dollar-sign + contextual formats, person names, domains, hashtags) + LLM extraction for high-importance units (>= 70)
- Knowledge graph: NetworkX DiGraph with JSONL persistence, wired at startup
- Reflection loop (ACE pattern): quality scoring, fingerprint dedup, conflict detection (importance divergence > 40 on shared tags), promote/demote tiers
- Both consolidation paths (`consolidate()` + `consolidate_v2()`) reindex ChromaDB to prevent ghost entries
- Working Context: hybrid relevance scoring (60% vector similarity + 40% keyword), mid-day refresh preserves access tracking

**Data:** `data/memory/` (units.jsonl, chromadb/, knowledge_graph/, working_context/)

**API Endpoints (9 new, all auth-verified):**
- `POST /memory/consolidate-v2`, `GET /memory/typed-stats`, `POST /memory/score`, `POST /memory/extract-entities`
- `GET /memory/knowledge-graph/stats|entity/{name}|top-entities|path|prune`

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
- **FirstStrike iOS**: 72+ commands, Brain Direct + Relay dual-mode, 5 tabs (Dashboard/Stocks/Intel/Journal/Settings), Dashboard = Overview + Chat + Strike Point unified
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
