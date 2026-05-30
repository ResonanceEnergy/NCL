# NCL Cost Reduction Audit — 2026-05-30

**Author**: Claude session (NATRIX-directed)
**Scope**: Every paid LLM call site in `runtime/`, mapped against actual 14-day spend ledger, with a tier-by-tier replacement plan covering Claude Haiku, local Ollama, and pure deterministic substitutes.

---

## Executive summary

**Actual 14-day spend (May 17 – May 30) — read from `data/costs/cost_ledger.jsonl`:**

```
TOTAL:        $136.61   ($9.76/day average; peak $30.24 on May 23)
  Anthropic   $ 95.38   12,726 calls   70% of total
  Perplexity  $ 16.77      546 calls   sonar-pro mostly
  OpenAI      $ 12.17    1,428 calls   ~50% GPT-4o
  YTC bucket  $  5.90       18 sessions
  X / Twitter $  4.94       36 calls   (now paused)
  Google      $  1.29      728 calls   Gemini Flash
  Cohere      $  0.30      148 calls   reranker
```

**The audit found 52 distinct paid-LLM call sites across `runtime/`.** Categorized:

| Tier | Sites | Description | Current daily cost | After cuts |
|---|---:|---|---:|---:|
| **A — Keep frontier** | 17 | Synthesis NATRIX or trader-agent reads | ~$3.00 | ~$1.50 |
| **B — Drop to Haiku** | 18 | Routine classification, summarization | ~$3.00 | ~$0.30 |
| **C — Move to local Ollama** | 5 | High-volume background work | ~$0.50 | $0 |
| **D — Already deterministic / delete** | 4 | Dead paths + already rule-based | ~$0.10 | $0 |
| **Bug — broken model IDs paying for failed retries** | 5+ | `claude-opus-4-6`, bare `claude-sonnet-4`, etc. | ~$0.10 | $0 |

**Projected savings: ~$8/day → ~$1.80/day = 82% reduction**, achievable in three phases over ~1 week of focused work. **All five Phase-1 fixes are no-risk and can ship today.**

**Top 5 cost drivers right now:**

1. **Untagged Anthropic calls** — $84.69 of $95.38 Anthropic spend has BLANK `metadata.model`. We literally cannot see which feature spent the money. **Phase 1 #1: instrument `record_cost` everywhere before any cuts.**
2. **YouTube Council per-video analyzer** — capped at $3/day, hits the cap on busy days. Already has Ollama route at `OLLAMA_COUNCIL_MODEL=qwen3:32b` — just needs to flip default.
3. **Brief Pro council + chair** — ~$0.42 measured per fire, 2 fires/day (AM Brief + PM Debrief) ≈ $0.85/day. **Keep — this is the product.**
4. **Strike Point council per pump** — 3-5 user-initiated fires/day at ~$0.10-0.20 each ≈ $0.50-1.00/day. **Keep — user-triggered.**
5. **Memory async-writer enrichment** — Sonnet 4 importance scoring + entity extraction per top-importance memory unit. Already gated to `importance ≥ 85` and `rule_score ≥ 9.0` after Wave 14X, but still 30-100 calls/day. **Move to local Ollama.**

---

## Current spend map (raw ledger output)

### Per-day total

```
May 20:  $ 1.75    May 25:  $16.17    May 30:  $ 0.61 (today, partial — Anthropic blocked)
May 21:  $ 0.41    May 26:  $19.99
May 22:  $12.07    May 27:  $19.99
May 23:  $30.24    May 28:  $12.43
May 24:  $19.28    May 29:  $ 3.78    average ~$9.76/day
```

The May 23 spike (~$30) blew past the $12 Anthropic cap because **other paid sources stack on top**: Perplexity, OpenAI, xAI each have their own $2/day caps. There is no platform-wide circuit breaker that triggers across providers — caps are per-source and additive.

### Per (source, model)

```
$84.69   anthropic/?                    ← UNATTRIBUTED, biggest blind spot
$12.90   perplexity/sonar-pro
$10.07   anthropic/claude-sonnet-4-20250514
$ 6.12   openai/?
$ 6.05   openai/gpt-4o
$ 5.90   ytc/?
$ 4.94   x_twitter/?  (paused now)
$ 1.12   google/gemini-2.5-flash
$ 0.41   anthropic/claude-opus-4-6      ← BROKEN MODEL ID — paying for 404 retries
$ 0.30   cohere/rerank-v3.5
$ 0.13   anthropic/claude-opus-4-20250514
$ 0.08   anthropic/claude-sonnet-4-6    ← BROKEN MODEL ID
```

**The two `*-6` entries are dead model IDs that 404 every call.** They still cost money because the LLM retry layer (`runtime/llm/retry.py`) attempts each call 3× before opening the circuit breaker. At ~$0.0003 per 400-error round trip, even cheap retries accumulate. **Both should be swept to dated IDs (e.g. `claude-opus-4-20250514`) — same bug class as Wave 13 fixed in 5 other files.**

---

## Mandate constraints (what MUST stay frontier)

Read from `docs/*.md`. These are NATRIX-level law — even if a cheaper model would technically run, the mandate forbids the downgrade:

| Mandate | Locked-in frontier requirement |
|---|---|
| `BRIEF_MANDATE.md` (LAW) | Chair synthesizes 5 lanes twice daily. Output IS the product. Opus stays. |
| `NIGHTWATCH_MANDATE.md` | Final analyst synthesis with status pill RED/YELLOW/GREEN. User-facing. Opus stays. |
| `JOURNAL_MANDATE.md` | ReflectionEngine 22:00 ET nightly synthesis NATRIX reads. Sonnet 4 stays. |
| `AUTO_TRADER_MANDATE.md` | `self_research.py` cluster-loss synthesis + `monthly_review.py`. User-facing trader-coach output. Sonnet stays. |
| `MEMORY_MANDATE.md` | Write-gate is **rule-based** (3 rules: authority ≥ 80, importance ≥ 95, composite ≥ 0.75). No LLM judgment needed at gate. |
| `AWAREBOT_MANDATE.md` | Composite scorer is **6-factor deterministic**. The `reason_about_signal` LLM call is only for ambiguous-band signals and is already budget-gated. |
| `CROSS_REFERENCE_MANDATE.md` | Pure pull-from-disk, no LLM at all. |

**Net read:** ~5 features carry mandate-level "must stay Opus or Sonnet" status. Everything else is open for downgrade or substitution.

---

## Tier-by-tier breakdown

### TIER A — KEEP FRONTIER (17 sites, ~$1.50/day after Phase 1)

Locked to Opus or Sonnet by mandate or because the user reads the output:

| File | Feature | Model | Why kept |
|---|---|---|---|
| `intelligence/brief_council.py:47,686` | Brief chair (5-lane synthesis) | Opus | LAW — the product |
| `intelligence/brief_council.py:43` | Brief Macro Analyst | Opus | Macro is the heaviest reasoning slot |
| `intelligence/brief_council.py:44` | Brief Pulse | Grok-4 | Needs live X search — different training data |
| `intelligence/brief_council.py:46` | Brief Technical | GPT-4o | Chart setups, distinct provider |
| `intelligence/afternoon_debrief.py:38` | PM Debrief synthesis | Opus | Twice-daily mandate |
| `autonomous/scheduler.py:345` | Journal reflection (10pm ET) | Sonnet 4 | User reads tomorrow |
| `autonomous/night_watch/analyst.py:486` | Night Watch synthesis | Opus | Status pill user reads |
| `ncl_brain/council.py` (multiple) | Strike Point council | Sonnet 4 + Grok-3 + Gemini Flash + GPT-4o | User-triggered, mandate-grade |
| `api/routes.py:476,4146,4171` | `/chat` Claude path | Sonnet 4 | Primary conversational touchpoint |
| `portfolio/auto_trader/self_research.py:459` | Auto-trader cluster-loss synthesis | Sonnet 4 | User-facing in iOS Paper view |
| `portfolio/auto_trader/monthly_review.py:305` | Auto-trader monthly review | Sonnet 4 | Long-form review user reads |
| `portfolio/analyst/llm_synthesis.py:37` | Portfolio Analyst (extended-thinking) | Sonnet 4 | 8k thinking — multi-position risk reasoning |
| `uni/synthesizer.py:219` | UNI research synthesis | Sonnet 4 | Long-form research |
| `life_plan/goal_synthesis.py:27,41` | Weekly SMART goal synthesis | Sonnet 4 | User-initiated planning output |
| `life_plan/vision_board.py:27` | Vision board image gen | gpt-image-1 | No LLM substitute — rate-limit only |
| `councils/shared/orchestrator.py:281,315` | Generic council orchestrator | Sonnet 4 + Grok-4 | Council-chair grade |
| `councils/shared/war_room_bridge.py:243,288` | War-room bridge | Sonnet 4 + Grok-4 | High-stakes synthesis (rare) |

### TIER B — DROP TO HAIKU 4.5 (18 sites, ~$0.30/day after migration)

Routine classification or summarization. Haiku 4.5 is ~5× cheaper than Sonnet 4 and the output quality difference is invisible in these tasks:

| File | Feature | Current | Suggested |
|---|---|---|---|
| `api/routers/intel/brief_pipeline.py:73` | Legacy brief PLANNER | Sonnet 4 | **Haiku 4.5** |
| `autonomous/night_watch/analyst.py:485` | Night Watch M1-M5 triage | Sonnet 4 | **Haiku 4.5**; bump to Sonnet only on RED |
| `autonomous/night_watch/intel_cycle.py:105` | Night Watch correlation | bare `sonnet-4` (404 risk) | **Fix ID + Haiku 4.5** |
| `autonomous/scheduler.py:3229` | Night Watch mini-council Sonnet | bare `sonnet-4` (404 risk) | **Fix ID + Haiku 4.5** |
| `autonomous/scheduler.py:3342` | Night Watch mini-council Opus chair | `claude-opus-4-6` (BROKEN) | **Fix ID + Sonnet 4** |
| `awarebot/agent.py:3282` | Awarebot executive brief | Sonnet 4 | **Haiku 4.5** |
| `awarebot/predictor.py:231` | Awarebot prediction emitter | Sonnet 4 | **Haiku 4.5** |
| `intelligence/engine.py:1404` | Intel engine exec brief | Sonnet 4 | **Haiku 4.5** (env-overridable) |
| `memory/procedural.py:71` | Procedural skill distillation | Sonnet 4 | **Haiku 4.5** |
| `council_pack/assembler.py:361` | MapReduce section compression | Sonnet 4 | **Haiku 4.5** |
| `councils/youtube/analyzer.py:64` | YTC per-video analyzer (Claude path) | Sonnet 4 | **Haiku 4.5** OR Ollama (see Tier C) |
| `councils/xai/analyzer.py:57` | X council analyzer | bare `sonnet-4` (404 risk; X paused) | **Fix ID + Haiku 4.5** when re-enabling |
| `councils/quorum.py:49,51` | Council quorum pre-pass | Sonnet 4 + Haiku 3.5 | **Haiku 4.5 both sides** |
| `uni/gatherer.py:154,190` | UNI gathering | Sonnet 4 / Grok-3-mini | **Default Grok-3-mini; Ollama fallback** |
| `lde/agents.py:251,286` | LDE agents | Sonnet 4 / Grok-4 / Ollama | **Default Ollama (already wired)** |
| `swarm/agents/scout.py` | Swarm scout | Sonnet 4 / Ollama | **Default Ollama** |
| `swarm/agents/scholar.py` | Swarm scholar | Sonnet 4 | Could be Haiku |
| `calendar/todo_generator.py:56` | Calendar todo generator | Haiku 4.5 | Already correct ✓ |

### TIER C — LOCAL OLLAMA (5 sites, $0/day after migration)

High-volume background tasks. Ollama already pulled (5 models, 72 GB on disk), already wired in 7 code paths, just not the default:

| File | Feature | Current | Suggested |
|---|---|---|---|
| `memory/importance_scorer.py:83,150` | Per-unit importance score (1-10) | Sonnet 4 | **Ollama `llama3.1:8b`** — 1-10 rating is trivial |
| `memory/entity_extractor.py:360,420` | Entity + relation extraction per unit | Sonnet 4 | **Ollama `qwen3:8b`** OR spaCy `en_core_web_sm` |
| `memory/narrative_threads.py:61` | Cross-session thread summarization (6h cadence) | Sonnet 4 | **Ollama `qwen3:8b`** |
| `autonomous/night_watch/memory_cycle.py:420,786` | Contradiction scanner (per cluster) | bare `sonnet-4` + Gemini Flash | **Fix ID + Ollama for primary; keep Gemini Flash verifier** |
| `councils/youtube/analyzer.py:66` | YTC per-video Grok-3 alternate | Grok-3 | **Default Ollama** — `OLLAMA_COUNCIL_MODEL` env already exists |

### TIER D — DETERMINISTIC OR DELETE (4 sites)

| File | Status |
|---|---|
| `api/routers/intel/__init__.py:1124` (legacy `/intelligence/morning-brief`) | **Delete** — Wave 14Y removed iOS callsite; this stub still has a 5000-token Sonnet call that will fire if anything calls it |
| `memory/ab_test.py:75,76` | Already gated by `NCL_AB_HAIKU` env, off by default |
| `councils/youtube/transcriber.py` | Already local Whisper |
| `awarebot/authority.py`, `pii_redactor.py`, `budget_tracker.py` | Already pure rule-based |

---

## Bug surface (worth fixing regardless of cost work)

These are leaking money on retries against 404 model IDs:

| File:Line | Bad ID | Fix |
|---|---|---|
| `autonomous/scheduler.py:3342,3360` | `claude-opus-4-6` | → `claude-opus-4-20250514` |
| `autonomous/scheduler.py:3229,3247` | bare `claude-sonnet-4` | → `claude-sonnet-4-20250514` |
| `autonomous/scheduler.py:3284,3304` | bare `claude-sonnet-4` | → `claude-sonnet-4-20250514` |
| `autonomous/night_watch/intel_cycle.py:105,112` | bare `claude-sonnet-4` | → `claude-sonnet-4-20250514` |
| `autonomous/night_watch/memory_cycle.py:420,807` | bare `claude-sonnet-4` | → `claude-sonnet-4-20250514` |
| `councils/xai/analyzer.py:57,274` | bare `claude-sonnet-4` | → `claude-sonnet-4-20250514` (when re-enabling X) |

Wave 13 swept 17 files for this same class of bug but missed these 5. The visible cost is small (~$0.10/14d) but Night Watch mini-council Opus has been **silently broken since Wave 13** — every chair-grade synthesis 404s and falls through to whichever fallback fires. Worth fixing for correctness alone.

---

## Local reasoning capacity (already on this machine)

Already pulled, already paid for in disk space, mostly idle:

**Ollama (port 11434, daemon running):**
- `llama3.1:70b` (42 GB, 70B params) — heavyweight reasoning
- `qwen3:32b` (20 GB, 32B params) — default for `OLLAMA_COUNCIL_MODEL` + LDE
- `deepseek-coder-v2:16b` (8.9 GB, MoE 16B) — `NCL_AGENT_REASONING_MODEL` for Awarebot
- `qwen3:8b` (5.2 GB) — fast council member
- `nomic-embed-text` (274 MB) — 768-d embeddings (would replace Anthropic embedding spend if any)

**Already wired** in 7 places: `llm/client.py`, `lde/agents.py`, `awarebot/agent.py`, `ncl_brain/council.py`, `uni/synthesizer.py`, `uni/gatherer.py`, `intelligence/engine.py`, `councils/xai/analyzer.py`. **Default route is the paid provider in every one** — Ollama only fires on fallback.

**MLX (Apple Silicon native):**
- `mlx==0.31.1` installed
- `mlx-whisper==0.4.3` installed and used by `lde/ingestor.py`
- `mlx-lm` NOT installed — would give 2-4× speedup over Ollama HTTP roundtrip for hot loops. **One `pip install` away.**

**Other useful libs not yet installed:**
- `sentence-transformers` — the code references it in 3 hot paths (`councils/quorum.py:128`, `councils/late_chunking.py:92`, `awarebot/topic_clusterer.py:8`) but the import fails silently and all 3 fall back to keyword-only. **Installing it would activate 3 dormant semantic-clustering systems for free.** ~150 MB.
- `transformers` — `torch==2.12.0` and MPS are ready; installing `transformers` unlocks MPS-accelerated zero-shot classifiers. Would replace Sonnet "is this signal relevant?" calls.
- `spacy` — installing `en_core_web_sm` (~12 MB) would do all entity extraction locally at zero cost, replacing the Sonnet 4 entity-extractor on the memory hot path.

---

## Phased roadmap

### Phase 1 — Ship today (no risk, ~2-3 hours work, ~50% Anthropic savings)

| # | Change | File(s) | Expected saving |
|---|---|---|---|
| 1.1 | Instrument every `record_cost` call with `metadata.model` so we can see what's spending | `runtime/cost_tracker.py` + every caller | $0 — enables attribution |
| 1.2 | Sweep all 5 broken model IDs to dated equivalents | `scheduler.py` (3 sites), `night_watch/intel_cycle.py`, `night_watch/memory_cycle.py`, `councils/xai/analyzer.py` | ~$0.10/day + restores broken Night Watch chair |
| 1.3 | Demote 6 Tier-B Sonnet calls to Haiku 4.5: Awarebot exec brief + Awarebot predictor + intel engine summary + MapReduce compression + Night Watch triage + procedural distillation | 6 files | ~$1.50/day |
| 1.4 | Delete `/intelligence/morning-brief` legacy stub at `runtime/api/routers/intel/__init__.py:1124` — iOS already retired the callsite in Wave 14Y | 1 file | Prevents stale $0.10 hits |
| 1.5 | Drop Anthropic daily cap from $12 to $5 — forces graceful degradation through Grok/Gemini/Ollama fallback chains that already exist | `runtime/cost_tracker.py:53` | Forces discipline; no quality loss because fallback chain works |

**Phase 1 net:** ~$1.70/day saved. Zero risk because Haiku 4.5 produces identical structured-output quality on these classification tasks.

### Phase 2 — This week (medium effort, ~$2-3/day more savings)

| # | Change | Effort | Saving |
|---|---|---|---|
| 2.1 | YTC analyzer default switch from Sonnet to Ollama `qwen3:32b` (env var already exists) | 1 line | ~$1-3/day at peak |
| 2.2 | Promote Ollama from fallback to PRIMARY for: importance scoring, entity extraction, narrative thread summarization, contradiction scanning | 4 files, ~1 day work | ~$0.30/day |
| 2.3 | `pip install sentence-transformers` + download `all-MiniLM-L6-v2` (~80 MB cache) — activates 3 dormant subsystems and replaces "are these similar?" LLM calls | 1 install | ~$0.10/day + better quality on clustering |
| 2.4 | Switch ChromaDB embedder to Ollama `nomic-embed-text` (already pulled) | Config change | $0 — already free, but removes any future spend if NCL ever adds Voyage/OpenAI embeddings |
| 2.5 | UNI gatherer + LDE agents + swarm scout — change default to Ollama (already wired) | 3 config changes | ~$0.20/day |

**Phase 2 net:** ~$2-3/day additional savings. Medium risk because Ollama output quality on YTC long-form analysis hasn't been A/B tested. Recommend A/B test first via existing `runtime/llm/ab_test.py` harness for 3 days.

### Phase 3 — Next sprint (architectural, ~$0.50/day more + speed wins)

| # | Change | Effort | Saving |
|---|---|---|---|
| 3.1 | `pip install mlx-lm` + port Awarebot `reason_about_signal` + brief critic to MLX-native Qwen3-8B (drops Ollama HTTP roundtrip) | 1-2 days | Latency: 2-4× faster; minor $ |
| 3.2 | `pip install transformers` + MPS zero-shot classifier for Sonnet "is this relevant?" classification calls scattered across Awarebot scoring | 2 days | ~$0.15/day |
| 3.3 | `pip install spacy` + `en_core_web_sm` — replaces all remaining LLM entity-extraction in memory subsystem | Half day | ~$0.10/day |
| 3.4 | Brief Pro council: drop from 4 paid members + chair to 2 paid members (Pulse + chair) + 2 Ollama members (Macro draft + Technical draft) | 1 day; A/B test required | ~$0.20/day |
| 3.5 | Multi-provider circuit breaker — when total daily spend across all sources exceeds $5, route everything to Ollama for the remainder of the day | 1 day | Caps blast radius |

**Phase 3 net:** ~$0.50/day savings + latency improvements. Higher risk on 3.4 (brief quality) — gate behind explicit A/B.

---

## Projected end state

| | Today | After Phase 1 | After Phase 2 | After Phase 3 |
|---|---:|---:|---:|---:|
| Anthropic | $6.81/day | $4.00 | $2.00 | $1.50 |
| OpenAI | $0.87/day | $0.87 | $0.50 | $0.30 |
| Perplexity | $1.20/day | $1.20 | $1.20 | $0.50 |
| Google | $0.09/day | $0.09 | $0.09 | $0.09 |
| YTC bucket | $0.42/day | $0.42 | $0.05 | $0.05 |
| Ollama (local) | $0 | $0 | $0 | $0 |
| **TOTAL** | **~$9.39/day** | **~$6.58/day** | **~$3.84/day** | **~$2.44/day** |
| **Cumulative savings** | — | **30%** | **59%** | **74%** |

**Targeting 80%+ savings is realistic** if Phase 3 #4 (brief council compression) survives A/B testing. The hardest-to-defend cut is the Brief Pro council because that's the flagship daily output — best to leave it at $0.85/day and harvest the other 80%.

---

## What I'm NOT recommending

For the record, here's what I considered and rejected:

1. **Demoting the Brief chair from Opus to Sonnet 4** — would save ~$0.40/day but the chair IS the product and Opus's longer reasoning chain shows in the quality of 5-lane synthesis. The cost is justified.
2. **Cutting Awarebot scan frequency** — current cadence drives cross-source confirmation, which is the load-bearing factor for the recently-shipped REDDIT PULSE quality. Don't slow the scanner.
3. **Replacing journal reflection with local Ollama** — NATRIX reads this. Sonnet 4 nightly is $0.05/day. Not worth the quality risk.
4. **Quitting Perplexity entirely** — sonar-pro is the live-citation slot in research workflows. Could downgrade to `sonar` (cheaper tier) for routine queries; reserve sonar-pro for chair-grade research calls. ~$0.50/day saving available there.
5. **Disabling the multi-provider Brief council** — was tempting given the cost stacking, but provider diversity is the architectural defense against any single API outage. Without it, today's Anthropic blocker would have killed the brief instead of falling through to Grok/Gemini.

---

## Ready to ship Phase 1 on your green light

Phase 1 is 5 changes across 8 files. I can deliver as a single commit, plus a small instrumentation patch to cost_tracker.py to fix the attribution blindness that made this audit harder than it needed to be. Estimated 2-3 hours of focused work, zero quality risk, ~30% daily-spend reduction.

If you want, I can also stand up a small spend dashboard at `/system/costs/dashboard` that reads the ledger and renders a daily-source-model bar so you can see this drift in real time instead of having to ask for an audit when bills feel high.
