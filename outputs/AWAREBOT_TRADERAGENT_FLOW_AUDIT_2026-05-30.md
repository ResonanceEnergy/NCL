# AWAREBOT & TRADERAGENT — Data Flow & Quality Audit (2026-05-30)

Status: complete. Auditor: read-only inspection of `runtime/`, `data/`, on-disk JSONL state. No live API probes (Brain process not interrogated). Every claim cites file:line or a specific data artifact.

---

## Executive Summary

1. **TRADERAGENT has never opened a single paper trade.** 106/106 reasoning chains in `data/portfolio/auto_trader/reasoning_chains.jsonl` show `policy_check.eligible: false`. All 14 paper trades in `data/paper_trading/trades.jsonl` were opened manually with `scanner_data: NULL` → outcome attribution coverage from auto_trader = **0%**. EOD summaries 5/26 → 5/30 all show `opens_today: 0`. The whole auto-trader stack downstream of the loop (bandit, drift, SHAP, graduation, self-research, friction calibration) is starved.

2. **The Pro Brief never registers its trade_ideas with the tracker.** `runtime/api/routers/intel/__init__.py:1433-1510` (`/morning-brief/pro/fire`) and the scheduled Wave 14H presenter both write a JSON envelope to disk but do NOT call `record_trade_idea_emission()`. Only the legacy Phase-B `brief_pipeline.py:607` calls it. Today's brief (`data/morning-brief-pro/2026-05-30.json`) contains 5 valid stock ideas (MSFT/etc.) that the auto-trader will never see. This is the single dominant cause of #1.

3. **Brief LLM is dumb-copying the placeholder string `"sig_id"`** verbatim into citation/sources arrays (see `trade_ideas[*].sources == ["sig_id"]` in today's brief). Root cause: chair prompt template `runtime/intelligence/brief_council.py:262, 268-270` uses the literal token `"sig_id"` as the example value in the schema. Even when the LLM provides a sources list, policy gate `runtime/portfolio/auto_trader/policy.py:258` would still pass it (non-empty), but the resulting citation is meaningless to any downstream consumer. The intel lane `top_signals` and `polymarket_watch` are equally polluted.

4. **Trade-idea tracker has no `sources` field at all.** `TradeIdea` dataclass at `runtime/portfolio/trade_idea_tracker.py:72-95` defines no `sources: list`. `record_emission()` at line 189-216 accepts a `metadata=` kwarg but `scanner.py:588` (scanner:goat path) doesn't pass it. Result: every scanner-emitted idea fails policy gate "no source citations" forever. **20% of all auto-trader rejects** (21/106) are this exact reason.

5. **The new ticker-universe whitelist (Wave 14CM, commit 8143cb9 @ 2026-05-30 21:06 MT) is not preventing junk promotions.** Cross-reference promotions at 2026-05-31 02:05 UTC include `NEVER`, `ONLY`, `REST`, `OS`, `HR`, `YOUR`, `THEY`, `PC`, `DTCC`, `DON`. `is_valid_ticker()` correctly rejects all of these when called directly. Either (a) the Brain hasn't been bounced post-14CM, or (b) the BERTopic theme-enrichment path at `cross_reference/__init__.py:188-210` is creating `bt:` cluster IDs that skip the whitelist entirely.

6. **Trend tracker is producing 58/98 alerts (60%) that are all false-positive `fading_100pct`** triggered by sparse data + arithmetic bug. Only 4 days of signals exist (start 5/27); the rollup divides by `7.0` (line 218) and `30.0` regardless of how many days are present, so `baseline_7d_daily_avg` is severely inflated, making `ratio_vs_7d = 0` for any low-volume ticker that wasn't mentioned in last 24h.

7. **News+trends double-verifier rule is structurally broken.** All 10 emitted promotions for that rule are sports/garbage (NBC, NY, AL, NBA, CBS) extracted from Polymarket promo-code article titles ("Polymarket promo code ELITE: Team USA World Cup — AL.com"). The 2-letter-min ticker regex + state-abbrev / sports-league overlap with the news source means this rule's signal-to-noise is ~0%.

---

# PART A. AWAREBOT

## A1. Input inventory

Source counts in `data/intelligence/agent_signals.jsonl` (17,379 rows total, 4-day window 5/27 → 5/31):

| Source | Rows | Status | Notes |
|---|---|---|---|
| `reddit` | 8,982 | LIVE | 51.7% of pool. Wave 14CN trimmed to 10 tier-1 subs but no measurable drop yet. |
| `options_flow` | 4,116 | LIVE (UW) | Avg composite 0.441 — lowest. `metadata.ticker = null` in samples; ticker enrichment Wave 14CN promised is not visible on-disk. |
| `google_trends` | 1,914 | LIVE | Pytrends. |
| `youtube` | 1,153 | LIVE | YTC per-video reports + scrapes. |
| `polymarket` | 473 | LIVE | Public REST. |
| `youtube_search` | 386 | LIVE | Wave 14CN reset to 6 queries (XRP, SLV, GLD, XRP ETF, OPTIONS FLOW, CAPITAL ROTATION). |
| `news` | 290 | LIVE | NewsAPI/GNews/RSS. |
| `city_events:*` | 65 (sum) | LIVE | 7 cities. Tiny volume (~10/city). |
| `youtube_council` | **0** | **PHANTOM** | `cross_reference/__init__.py:49` whitelists this source but no row in `agent_signals.jsonl` has it. YTC reports persist as `source=youtube`. |
| `x_twitter` / `x` | 0 | DISABLED | Per CLAUDE.md. |
| `crypto` | 0 | DISABLED | CoinGecko rate-limit. |

Volume per day:
- 5/27: 4,174 — 5/28: 5,873 — 5/29: 2,166 — 5/30: 2,639 — 5/31: 2,527 (partial). 5/29 drop coincides with Wave 14CG signal-dedup tightening; the recovery to ~2.5k/d suggests dedup is now stable.

Route-level distribution (full file): 7,034 HIGH, 9,069 MEDIUM, 412 CRITICAL, ~862 unclassified. Tail of last 1000 signals: 0 CRITICAL, 153 HIGH, 847 MEDIUM. CRITICAL emission has dried up entirely in the last ~12h, consistent with Wave 14W-B raising `THRESHOLD_HIGH` from 0.55 → 0.65 (`agent.py:94`) plus Wave 14CN promo-cap on YouTube SEARCH.

Avg composite by source (full pool):
- `news` 0.722, `youtube` 0.699, `polymarket` 0.651, `youtube_search` 0.638, `city_events:edmonton` 0.607, `reddit` 0.598, `google_trends` 0.588, `city_events:*` 0.51-0.59, `options_flow` 0.441.

`options_flow` at 0.441 average + 4,116 rows is producing the lowest-quality signal at the highest volume. Cost-vs-value: the UW API is hit hard every cycle and the resulting MEDIUM-bucket signals never make it to a brief or council, just memory + STREAM. Worth a separate audit.

## A2. Transform pipeline

```
SCAN → SCORE → ROUTE → PERSIST → CROSS-REF → TREND → BRIEF
```

### A2.1 SCAN — `Awarebot.run()` → `_scan_*` methods, agent.py
- ReAct loop. Per-source rate-limited via `TokenBucket` (`agent.py:402-427`).
- 8 active scanners: `_scan_reddit`, `_scan_youtube`, `_scan_youtube_search`, `_scan_google_trends`, `_scan_polymarket`, `_scan_news`, `_scan_options_flow`, `_scan_city_events`. X/crypto disabled.
- Recently added (Wave 14CG): `agent.py:296-330` SignalFingerprint tightened to dedup against fingerprint store across cycles. Cut volume ~10-15%.
- Wave 14CH: `_PROMO_MARKERS` list (`agent.py:187-238`) caps creator-sponsored YouTube videos at MEDIUM. List is keyword-only — generates false-positives ("subscribe", "tutorial:", "in 2025"). Observability: `signals_dropped_promo` counter exists but I did not check live stats.
- Wave 14CN: hollow-skip (empty content + title==content + no url → drop, `agent.py:4640-4647`). Counted as `signals_dropped_hollow`.

### A2.2 SCORE — `score_signal()` agent.py:2008-2174
7-factor composite per `compute_composite_score()` agent.py:435-465. Weights: `relevance 30% / freshness 20% / cross_source 15% / source_confidence 15% / actionability 10% / novelty 5% / situational 5%`. Sum = 1.00. Pure deterministic, fully tested.

- Relevance: 70% BM25 (against `_watch_queries` from all sources) + 30% scanner-provided; then blended 50/50 with mandate/working-context keyword score.
- Novelty: SimHash near-dup + exponential decay. SimHash index bounded to 10K entries, 20% LRU prune (`agent.py:2058-2064`).
- Authority: 80% computed (engagement + platform base) + 20% scanner-provided. Then blended 70/30 with `AuthorityLearner` posterior (Beta-Bernoulli).
- Cross-source: prefer `EntityClusterer.ingest()` (6h window entity+sector graph) at `agent.py:2114-2122`; fall back to token-Jaccard. **Silent failure**: clusterer errors get debug-logged only.
- Freshness: HN-gravity decay.
- Situational (Wave 14X-Y/14BL): pulls `_get_situational_ctx()` once per scoring batch (`agent.py:2134`). Adds +0.30 for theme overlap with `themes_active`. Cached 30 min.
- Local sentiment (Wave 14AU): FinBERT/Twitter-RoBERTa enrichment for social-source prefixes — adds ≤+0.15 to `actionability` for polarity > 0.5. Lazy-loaded, MPS-accelerated. **Observability gap**: no telemetry on hit rate or polarity distribution.

Score factors are persisted to `signal.metadata.score_factors` (Wave 14CH, `agent.py:2160-2168`). This is the only operator-visible breakdown — useful for debugging individual signal scores.

### A2.3 ROUTE — `_route_signal()` agent.py:2380-2407
Step-function on composite:
- `≥ 0.75` CRITICAL → all context windows + memory unit (importance 85) + working-context inject + push alert + flag `council_flagged` + write to `data/autonomous_signals/council_flags.jsonl` (Wave 14X-3-era envelope fix)
- `≥ 0.65` HIGH → 24h + 7d + memory unit (importance 65) + working-context inject
- `≥ 0.30` MEDIUM → 24h + 7d + memory unit (importance 40 nominal)
- `< 0.30` LOW → debug log only, skip all storage

Every routed signal is also appended to `_prediction_buffer` and persisted via `_persist_signal` regardless of level. LOW signals do NOT get persisted (they short-circuit before `_persist_signal`).

### A2.4 PERSIST — `_persist_signal()` agent.py:4623-4702
- Soft rotation at `NCL_AGENT_SIGNALS_ROTATE_BYTES` (default 50 MB). Cascades `.1 → .2`, dropping older `.2` (Wave 13 P2 fix to preserve history).
- Wave 14CG hollow-skip (4640-4647).
- Wave 14CJ write-side dedup window (`NCL_PERSIST_DEDUP_HOURS=4` default). Separate from ingest-side `_seen_fingerprints`.
- Bounded cache 5000 entries with 20% LRU prune. **Quality leak**: no telemetry on how many writes are dropped here.

### A2.5 CROSS-REF — `runtime/cross_reference/__init__.py`
Scheduler-driven (5 min cadence per CLAUDE.md, task `ncl-cross-reference`). Reads last 4h (ticker rule) + 24h (theme/news+trends) from `agent_signals.jsonl` via bounded tail read (5 MB).

3 rules:
1. `ticker_converge`: ≥2 distinct AWAREBOT sources within 4h. Source whitelist `_INTEL_SOURCES` at line 48 includes `youtube_council` and `ytc` (both never emitted by Awarebot).
2. `theme_converge`: ≥3 distinct sources within 24h. 5 hardcoded clusters (`rate_policy`, `ai_capex`, `energy_supply`, `crypto_macro`, `geopolitical`) + BERTopic enrichment.
3. `news_trends_double`: same ticker hit in news + google_trends on the same day.

Dedup by `(ticker, day)` key.

Output to `data/cross_reference/promotions.jsonl`: 89 total, last 7d shows 14 (5/29) + 41 (5/30) + 34 (5/31). By rule: 68 ticker_converge, 11 theme_converge, 10 news_trends_double.

### A2.6 TREND — `runtime/intelligence/trend_tracker.py`
Tails `agent_signals.jsonl`, extracts tickers via filtered regex, buckets by `(source, ticker, hour)`. Writes `data/trends/buckets-YYYY-MM-DD.json` + `alerts-YYYY-MM-DD.json`.

Today (`alerts-2026-05-31.json`): 98 alerts, **58 are `fading_100pct_vs_7d`** with `current_24h_mentions: 0` (broken — see A4). Only 38 are `spiking_*` (legit).

### A2.7 BRIEF — `runtime/intelligence/brief_council.py` + `brief_presenter.py`
Today's `data/morning-brief-pro/2026-05-30.json` was rendered 2026-05-30T18:46Z via the `/morning-brief/pro/fire` path with `members_succeeded: [macro, pulse, flow, technical]`. Council model IDs (`council_meta.macro_model` etc.) are all `null` in the persisted envelope — a separate observability gap.

## A3. Output sinks

| Sink | Format | Retention | Consumer |
|---|---|---|---|
| `data/intelligence/agent_signals.jsonl` | JSONL append | 50 MB rotation × 2 backups (~150 MB ceiling, ~13d at current rate) | trend_tracker, cross_reference, intel router (`/intel/now`, `/intel/stream`, `/intelligence/signals`) |
| `data/intelligence/agent_briefs.jsonl` | JSONL append | unbounded | brief_prep, latest_brief.txt, memory bridge |
| `data/intelligence/latest_brief.{json,txt}` | atomic write | overwrite | iOS Intel tab |
| MemoryStore via `_store_to_memory()` | MemUnit | governed by `MAX_TOTAL_UNITS=25000` + decay | working_context, FusedRetriever, brief_prep |
| `data/autonomous_signals/council_flags.jsonl` | JSONL append | unbounded | scheduler `_council_auto_loop` |
| ntfy push via `_push_alert` → AlertDispatcher | rate-limited | 1/10s, 1h dedup | NATRIX's phone |
| `data/cross_reference/promotions.jsonl` | JSONL append | unbounded (62 KB after 89 rows; will grow) | iOS Intel XREF chip, brief INTEL lane (when wired) |
| `data/trends/{buckets,alerts}-YYYY-MM-DD.json` | atomic overwrite | per-day file, retention manual | iOS Intel TRENDS sub-tab (?), brief macro context |
| Working context | in-process + persisted JSON | 50-cap, lowest-salience evict | chat injection, brief PREP CONTEXT, AWAREBOT scorer (situational factor) |

## A4. Quality leaks (AWAREBOT)

### A4.1 The "sig_id" placeholder bug — every brief contains literal junk
`runtime/intelligence/brief_council.py` defines the chair output schema with EXAMPLE values:
```python
"top_signals": [{{"text":"...","source":"...","sig_id":"..."}}],
"trade_ideas": [{{..."sources":["sig_id"]}}],
"polymarket_watch": [{{"text":"...","citations":["sig_id"]}}],
```
The LLM is interpreting `"sig_id"` (the EXAMPLE VALUE string) as a literal it should copy. Today's brief at `data/morning-brief-pro/2026-05-30.json` shows:
```
"trade_ideas": [..., {"ticker":"MSFT", ..., "sources":["sig_id"]}, ... × 5]
"top_signals": [{"text":"AI optimism evident from GRRR, PLTR gains","source":"reddit","sig_id":"sig_id"}]
"polymarket_watch": [{"text":"US x Iran...", "citations":["sig_id"]}]
```
Fix: change examples to `"sources":["sig_001","sig_042"]` and add an explicit "use real 8-char sig_ids from prep pack" rule near the top of the chair prompt. Currently rule 7 (`brief_council.py:248`) mentions "SOURCES citation list" but doesn't tell the LLM to use the actual values.

### A4.2 News+trends double-verifier is structurally noisy
Sample promotions (`promotions.jsonl`, 2026-05-29T18:00):
- NBC → "nbc / thunder vs spurs / Google employee charged..."
- NY → "Polymarket promo code ELITE: Team USA World Cup — Elite Sports NY / there she goes fox / nyc world cup lottery"
- NBA → "nba anti tanking / wemby okc / nj transit"
- AL → "Polymarket promo code ALCOM: Team USA World Cup — AL.com / twins vs white sox / alabama power"

Root causes:
1. The `_TICKER_RX` regex (`cross_reference/__init__.py:57`) matches 2-letter strings — perfectly overlaps with state abbrevs (NY, AL, NJ) and sports leagues (NBA, NHL, NFL, MLB).
2. `news` source ingests Polymarket affiliate posts where the article URL or title contains those substrings.
3. `google_trends` extracts the same tokens because the Trends source is open-ended.
4. `is_valid_ticker()` allows NBC, NBA, AL, NY as real listed tickers (NY is a real symbol; NBA is not but the universe is broad).

Fix: rule should require `len(ticker) >= 3` AND `ticker not in {"NBC", "NBA", "CBS", "NHL", "NFL", "MLB", "NCAA", "WNBA", "USA"}` (broadcast/sports stoplist), AND for `news_trends_double` specifically, gate on `source authority >= LLM_SINGLE` (i.e. drop affiliate-promo titles).

### A4.3 The Wave 14CM whitelist isn't pruning junk promotions
2026-05-31T02:05 UTC promoted: `NEVER, ONLY, REST, OS, HR, YOUR, THEY, PC, DTCC, DON, XLM`. I verified `is_valid_ticker(NEVER)` → `False`, `is_valid_ticker(THEY)` → `False`, etc. directly via subprocess. So either:
- (a) Brain hasn't been bounced after the 14CM commit (the 5-hour gap between commit 21:06 ET and bad-promo at 22:05 ET means the Brain was running stale code), or
- (b) `_extract_tickers` is being called from the BERTopic path which doesn't enforce the universe. The `bt:<label>` themes added at `cross_reference/__init__.py:208` skip the ticker check entirely; if BERTopic learned "they / never / only" as a topic label, that label could be hitting `theme_converge` and getting written with no ticker validation.

**Action**: bounce the Brain. If junk re-appears after bounce, the BERTopic per-source labels must be the source — inspect `data/cross_reference/bertopic_model/{reddit,youtube,...}/`.

### A4.4 `youtube_council` is a phantom source
`cross_reference/__init__.py:49` whitelists `youtube_council` and `ytc` in `_INTEL_SOURCES`, but `agent_signals.jsonl` has zero rows with that source. YTC per-video reports are emitted with `source = "youtube"` and tag `ytc-rollup`. Consequence: any cross-reference rule that requires `youtube_council` as a distinct source contributor under-counts YTC's contribution to convergence.

Either rename the YTC emission site (`agent.py:4514` area) to use `"youtube_council"`, or remove the phantom from `_INTEL_SOURCES`.

### A4.5 Trend tracker baseline arithmetic is wrong for short histories
`compute_alerts()` at `trend_tracker.py:208-210`:
```python
baseline_7d = sum(last_7d) / 7.0 if last_7d else 0
baseline_30d = sum(last_30d) / 30.0 if last_30d else 0
```
The divisor is HARDCODED to `7.0` and `30.0` regardless of whether the data file covers 7 or 30 days. Since `agent_signals.jsonl` only goes back to 2026-05-27 (4 days), the 7-day baseline is `actual_count / 7` instead of `actual_count / 4`. Then `ratio_vs_7d = current_24h / baseline_7d`. If `current_24h_mentions == 0` for any ticker that had ANY mention in last 4 days, the ratio is 0/positive → `fading_100pct` triggers.

Result: 58 of 98 alerts today (60%) are noise. Fix: use `actual_days = min(7, (now - earliest_ts).days)` as divisor.

Bonus: even after the bounce, `current_24h_mentions: 0` means the spike test (line 235-239) has zero numerator. The `fading` test is mathematically guaranteed to fire on any ticker that was mentioned 3-4 days ago but not today, which after Wave 14CG/14CN dedup pruning is most of the universe.

### A4.6 `options_flow.metadata.ticker = null` despite Wave 14CN ticker enrichment
Sampling current rows: `{"ticker": null, "title": "VIX flow alert: $553,950..."}` × 5 consecutive. The ticker IS in the title prefix but is not extracted into `metadata.ticker`. The cross-reference engine extracts tickers from `title + content` so this technically works, but any consumer that reads `metadata.ticker` directly (paper trade scanner data, brief portfolio lane) is getting null.

### A4.7 Stages with silent failure
- `EntityClusterer.ingest()` exception → `cross_source = 0.0` fallback, log.debug only (`agent.py:2121`). No counter.
- `AuthorityLearner` blend failure → log.debug only (`agent.py:2084`). No counter.
- `compute_situational_relevance` import failure → silent `pass` (`agent.py:2145`). No counter.
- `_PROMO_MARKERS` keyword cap → no per-marker telemetry. Can't tell which markers are firing most.
- BERTopic load failure → log.debug + `_bertopic_lookup_attempted = True` (`cross_reference/__init__.py:235`). One-shot; never retries.

### A4.8 Cost-vs-value: options_flow over-fires
4,116 rows × avg score 0.441 = a lot of MEDIUM noise. Score factors show low actionability + low cross-source for most rows because UW data isn't entity-clusterable (ticker in metadata is null per A4.6 — `EntityClusterer` can't bucket without a ticker tag). The signals reach memory + STREAM, but never CRITICAL/HIGH, so they never reach a brief's INTEL lane. Net effect: UW API spend + disk + ChromaDB writes with no operator-visible value.

### A4.9 BERTopic 8-model corpus is ~800 MB
`du -sh data/cross_reference/bertopic_model/*` shows 88M, 94M, 89M, 123M, 89M, 140M, 89M, 90M = **~810 MB total** for 8 source-stratified models. The global `model.pkl` is another 98 MB. Per CLAUDE.md, retrain is weekly Sun 04:00 ET. Disk pressure isn't critical, but the load time on first import is non-trivial and the noise filter (Wave 14BV) is fighting cluster labels that include English stop words — see A4.3 above.

---

# PART B. TRADERAGENT (auto_trader)

## B1. Input inventory

Two upstream feeders:

### B1.1 `trade_idea_tracker` (the only consumer the loop reads)
`runtime/portfolio/trade_idea_tracker.py:271-277`:
```python
async def list_by_strategy(self, strategy=None) -> list[dict]:
```
Returns all loaded `TradeIdea` objects as dicts, sorted by `issued_at_iso` DESC. Loop at `loop.py:262` filters to `outcome == "emitted"` and `issued_at_iso > state.last_seen_trade_idea_id`.

Current state: 112 lines in `trade_ideas.jsonl`, 109 unique ideas, 3 with outcome != emitted (1 stopped_out, 2 target_hit — these are leftover from the original 2026-05-26 NVDA/AAPL/AMD seed). Per-source:
- `quant:pairs` 46
- `scanner:goat` 36
- `brief` 30

**Critical**: brief contributions stopped on 2026-05-26 (Wave 14H seed days). The new Pro Brief path (Wave 14H+14Y) does NOT call `record_trade_idea_emission` — see B4.1. Scanner:goat last emitted 2026-05-29T22:02. quant:pairs last emitted 2026-05-27 (none on disk for last 4 days).

Last `last_seen_trade_idea_id` in `state.json`: `2026-05-29T22:02:12.959408+00:00`. Loop tick is current (`last_loop_tick_iso: 2026-05-31T03:47:10`) but there are zero unconsumed ideas.

### B1.2 Cross-reference promotions (advertised but not wired)
The CLAUDE.md spec says cross-ref bridges AWAREBOT → TRADERAGENT. The auto_trader loop does NOT import `cross_reference` or read `promotions.jsonl`. No consumer wiring exists. The promotions sit on disk producing iOS XREF chip only.

## B2. Transform pipeline (Gate Chain)

`auto_trader_loop` at `runtime/portfolio/auto_trader/loop.py:147-749`. Single tick (60s market / 300s off):

```
0. cycle_watcher (every 60 ticks) — bandit prior decay on regime transition
1. drawdown_bucket → set_drawdown_halt(band == 'halt')
2. state.is_active()
3. day-cap check (max_opens_per_day = 8 from policy.json)
4. pull tracker.list_by_strategy(None), filter to new emitted ideas
   FOR EACH new idea:
   4.5. sanity_gate (4 checks — ticker exists, price ∈ 52w range, daily |Δ| < 30%, vol > 0)
   5.   risk_governor (R-dollars, NAV fraction, strategy heat cap)
   6a.  calendar_gate (FOMC/OPEX/earnings windows)
   6b.  working_context_gate (NATRIX-tier pinned items contradicting ticker)
   6c.  policy.auto_open_eligible — 10 checks (stop type, R:R, sources, thesis, etc.)
   7.   compute qty + effective_R
   7a.  tax_sizing (wash sale + earnings proximity multiplier, optionally blocks)
   7b.  beta_cap + sector_cap exposure checks
   8.   friction_profile injection (slippage + partial fill)
   8.5. council_check (high-R trades only)
   9.   paper.create_trade() — wrapped in cb_paper circuit breaker
   10.  record_reasoning_chain + update_paper_trade_id + tracker.update_outcome("taken")
   11.  emit portfolio:auto_trade_opened MemUnit (importance 75)
12. state.record_tick — update counters + last_seen_iso
```

Each gate emits an observability record to `reasoning_chains.jsonl` on both PASS and REJECT (the loop records the chain at line 331-346 for sanity, 394-408 for calendar, etc.). Excellent observability **for ideas that reach the loop**. Zero observability for ideas that never reach the loop because they never made it into `trade_ideas.jsonl`.

### B2.1 Modules touched but unused
Per file inventory (32 modules, 12,149 LOC):

| Module | Last activity | Notes |
|---|---|---|
| `state.py` | 5/31 03:47 | LIVE — tick state persisted |
| `policy.py` | 5/27 01:14 | LIVE — rev 2, never reloaded |
| `loop.py` | LIVE | Main loop |
| `observability.py` | 5/29 22:02 | LIVE — 106 chains, all REJECT |
| `price_feed.py` | unknown | scheduler-driven (separate loop) |
| `outcome_attributor.py` | NEVER | 0 calls — depends on paper trades with `trade_idea_id` (none exist) |
| `strategy_bandit.py` | 5/26 22:31 | DORMANT — last update was during the manual NVDA/AAPL/AMD seed |
| `shap_attribution.py` | NEVER (no run output found) | DORMANT — fires every 10 closes per strategy; bandit has 1 close per strategy |
| `self_research.py` | NEVER (no `research_topics.json`) | DORMANT |
| `drift_detector.py` | NEVER (no `drift_state.json`) | DORMANT |
| `graduation_gate.py` | unknown | Endpoint exists; never gated by data |
| `friction_profile.py` | 5/26 23:07 | written; never calibrated (calibrate after 10 closes — never reached) |
| `quant_scanners.py` | 5/31 03:21 LIVE but `total_ideas_emitted: 0` for last ~50 ticks | DORMANT — scanners running but emitting nothing |
| `scout.py` | 5/31 03:51 | LIVE — emitting cc_opps=2, ed=2, pt=2, rs=2 per tick (probably constant placeholders) |
| `cycle_watcher.py` | 5/30 07:48 | LIVE — `last_seen_phase: late_cycle`, no transitions |
| `eod_summary.py` | 5/31 01:55 | LIVE — daily; correctly reports zero |

The auto_trader has 32 modules, ~12K LOC, sophisticated reasoning, observability, circuit breakers, friction modeling, drift detection — and **none of them have meaningful data to operate on**.

## B3. Output sinks

| Sink | Format | Retention | Consumer |
|---|---|---|---|
| `data/portfolio/auto_trader/state.json` | overwrite | live | iOS dashboard, loop |
| `data/portfolio/auto_trader/reasoning_chains.jsonl` | append | unbounded | iOS auto-trader detail view, retrospective analysis |
| `data/portfolio/auto_trader/recent_chains.json` | overwrite (~278 KB) | last N | iOS quick view |
| `data/portfolio/auto_trader/eod_summaries.jsonl` | append daily | unbounded | brief PORTFOLIO lane yesterday_recap |
| `data/portfolio/auto_trader/bandit_state.json` | overwrite | live | strategy ranking |
| `data/portfolio/auto_trader/quant_scan_events.jsonl` | append per scan | unbounded | scanner telemetry |
| `data/portfolio/auto_trader/scout_events.jsonl` | append per tick | unbounded | scout telemetry |
| `data/portfolio/auto_trader/friction_profiles.json` | overwrite | live | next open's slippage |
| `data/portfolio/auto_trader/cycle_watcher_state.json` | overwrite | live | cycle transitions |
| `data/portfolio/auto_trader/capability_state.json` | overwrite | live | upstream-data probe status |
| MemoryStore `portfolio:auto_trade_opened` units | MemUnit | importance 75 | working context, brief PORTFOLIO lane |
| `data/paper_trading/trades.jsonl` (via PaperTradingEngine) | append | unbounded | iOS Paper tab, attribution |

## B4. Quality leaks (TRADERAGENT)

### B4.1 [SHOWSTOPPER] Pro Brief doesn't register its trade_ideas
`runtime/api/routers/intel/__init__.py:1433-1510` is the canonical entry point for the morning brief today (Wave 14H+14Y). It calls:
- `build_prep_pack(brain)`
- `run_council(pack, api_key)`
- `render_pro_brief(synthesis, pack)` — pure renderer
- `memory_store.create_unit(...)` — snapshot to memory
- `_render_wav(text)` — TTS

It does NOT call `record_trade_idea_emission()`. Only `runtime/api/routers/intel/brief_pipeline.py:607` (the older Phase-B advisor pipeline) does, and that path is not hit by `/morning-brief/pro/fire`.

Result: today's brief has 5 valid stock trade ideas (MSFT, etc.) sitting in `data/morning-brief-pro/2026-05-30.json` with full entry/stop/target and the auto-trader has no idea they exist.

Fix scope: 30-50 LOC. After `render_pro_brief()` returns, iterate `envelope["lanes"]["portfolio"]["trade_ideas"]` and call `record_trade_idea_emission` for each (mirror `brief_pipeline.py:606-650`).

### B4.2 [SHOWSTOPPER] TradeIdea dataclass has no `sources` field
`runtime/portfolio/trade_idea_tracker.py:72-95`. The `TradeIdea` dataclass omits `sources`. `record_emission` at line 189-216 accepts `metadata: dict` but `runtime/stocks/scanner.py:588-595` (scanner:goat) doesn't pass it. The brief-pipeline path at `brief_pipeline.py:645-648` DOES pass `metadata={"sources": ...}` but that's nested in metadata — `asdict(idea)` flattens to a dict where `idea.get("sources")` is empty and `idea.get("metadata", {}).get("sources")` would be needed.

Then policy.py:258:
```python
sources = idea.get("sources") or []
if not sources:
    return False, "no source citations"
```

Result: 21/106 rejects (20%) are "no source citations". This will continue even after B4.1 is fixed unless either:
- (a) `TradeIdea` gains a top-level `sources: list[str]` field, OR
- (b) policy reads `idea.get("sources") or idea.get("metadata", {}).get("sources") or []`, OR
- (c) `record_emission` accepts `sources=` and promotes it to the top-level field.

(b) is the minimal fix; (a)+(c) is the correct fix.

### B4.3 The "atr_2x" normalization works in code but didn't unblock historical rejects
`policy.py:251-254`:
```python
root = str(stop_type).split("_")[0].lower()
if root not in {t.lower() for t in policy.valid_stop_types}:
    return False, f"invalid stop_type {stop_type!r}"
```
`atr_2x`.split('_')[0] == 'atr', and `'atr'` IS in `policy.valid_stop_types`. So this should pass. Yet reasoning_chains.jsonl shows 17 ideas rejected with "invalid stop_type 'atr_2x'" between 5/28 01:25 and 5/29 18:48. Either the Wave 14AA fix landed after those rejects, or the code path is somehow not reached.

Spot check: the policy_check timestamps show no rejects after 5/29 18:48 with this reason — newer ideas may already be bypassing. **Verify by replay**: re-run the 17 stuck ideas through `auto_open_eligible(idea, gov, policy=current_policy)` and confirm pass/fail.

### B4.4 Drawdown stuck at -100% due to NAV=$0 races
Reasoning chain reasons show 26 rejects from "Drawdown band=halt (dd=-100.0%). All new risk blocked." The loop has a NAV-data-unavailability guard at `loop.py:217-227`:
```python
if band == "halt" and nav_cad < 100:
    log.debug("... treating as data-unavailable, not halt")
    band = "unknown"
    await set_drawdown_halt(False, band="unknown")
```
But this guard is INSIDE the loop's drawdown read, while the rejected reasoning chains show the *governor*'s response carrying `band=halt`. The governor (`runtime/portfolio/risk_governor.py`) has its own read of the bucket that doesn't apply the NAV-guard logic. So at the moment the governor's read sees NAV=$0 (e.g. during portfolio sync race) it returns halt → idea rejected → loop's NAV-guard runs AFTER the governor and clears the band only for the NEXT tick. The race could be fixed by passing the loop's `band` into the governor call as an override.

### B4.5 Quant scanners are running but emit nothing
`quant_scan_events.jsonl` last 50 ticks: `total_ideas_emitted: 0` for every one. `scanners[*].emitted = 0` for all 7 scanners (mean_reversion, pead, factor, pairs, whale_flow, crypto_carry, polymarket_kelly). `watchlist_size: 16`.

Either the universe is too narrow (16 tickers), the entry criteria are too tight, or the data feed is missing. The last successful quant:pairs emissions were 2026-05-27, then silence. Worth a probe: log the per-scanner "candidates considered vs emitted" counts.

### B4.6 Outcome attribution coverage = 0%
`data/paper_trading/trades.jsonl`: 14 rows, all `status: closed_manual`, all `scanner_data.trade_idea_id: NULL`. These are NATRIX's manual closes from 5/29 18:03 (8 SLV / 5 GLD-XLE-XRP options + 1 XLE stock + 1 HOLO + 1 GOOG).

`outcome_attributor.py:55-62` extracts `trade_idea_id` from `paper_trade.scanner_data.trade_idea_id`. With 0 stitchable trades, the attributor has done zero work since deployment.

This is downstream of B4.1+B4.2; fixing those will start populating it. But the existing 14 closed manuals are PERMANENTLY orphaned from any source-attribution feedback loop.

### B4.7 `portfolio:auto_trade_opened` MemUnits = 0
`grep -c 'portfolio:auto_trade_opened' data/memory/units.jsonl` → 0. Of course (no opens). When B4.1+B4.2 unblock opens, this metric goes positive; right now it confirms the meta-loop (auto-trader memory units → brief → next-day prompts) is dead.

### B4.8 Strategy 'unknown' heat cap
9 rejects show "Strategy 'unknown' heat would breach cap". The MSFT ideas have `strategy="goat"` from the scanner, but `_normalize_strategy` returns 'unknown' for unrecognized strings. Either:
- The scanner emits `strategy=` value that doesn't map (`runtime/portfolio/risk_governor.py:_normalize_strategy`), or
- The brief idea has `strategy_tag` = something the normalizer doesn't recognize.

Result: governor's `effective_R = $2080` for a $36K NAV (5.78%) exceeds the `unknown` strategy's $1800 cap (5% of NAV). Fix: harden `_normalize_strategy` and add `unknown` cap fallback to 0 instead of 5%.

### B4.9 `scout_events.jsonl` constant payload
`scout_events.jsonl` last 2 ticks: `cc_opps=2, ed=2, pt=2, rs=2` — identical. Either scout is producing the same 2-opportunity result every tick (suggests stale cache or hardcoded fallback), or the same handful are being emitted forever. Worth dumping a sample.

### B4.10 Reasoning chains have no `metadata.brief_version` linkage
Every chain has `idea_snapshot` (full idea dict) but doesn't stamp the brief version or council session that produced the idea. When ideas come from `brief` source post-B4.1 fix, the chain can't easily say "this was the 2026-05-30 brief's #3 idea." Recommend adding `idea_snapshot.brief_id` and `idea_snapshot.council_session_id` for retrospective grouping.

---

# Top 10 highest-leverage fixes — ranked impact-vs-effort

| # | Fix | Impact | Effort | File:line |
|---|---|---|---|---|
| **1** | **Wire `/morning-brief/pro/fire` → `record_trade_idea_emission`.** This single fix is the difference between an auto-trader that has trades to evaluate (and the whole 12K-LOC stack waking up) vs one that's been completely starved for 4 days. | MASSIVE | 30 min | `runtime/api/routers/intel/__init__.py` after line 1464 + `runtime/intelligence/brief_council.py` similar hook for scheduled path |
| **2** | **Fix the `"sig_id"` literal placeholder in chair prompt.** Replace example values `"sig_id"` with `"sig_001"` / `"sig_042"` and add explicit "REPLACE WITH ACTUAL 8-char sig_id from prep pack" rule near the top. Cleans up brief output instantly. | HIGH | 15 min | `runtime/intelligence/brief_council.py:262, 268-270, 104, 143` |
| **3** | **Add `sources: list[str]` to TradeIdea dataclass + thread through `record_emission`.** Stops "no source citations" mass rejects, unblocks GOAT/quant scanner ideas. | HIGH | 30 min | `runtime/portfolio/trade_idea_tracker.py:72-216` |
| **4** | **Bounce the Brain to pick up Wave 14CM/14CN.** If junk ticker promotions (NEVER/REST/THEY) persist after bounce, then audit `bertopic_themes.classify_themes_for_source` — likely sending stop-word topic labels into theme_converge. | HIGH | 5 min bounce + 1h investigation if needed | — |
| **5** | **Fix trend_tracker baseline divisor for short histories.** Change `sum(last_7d) / 7.0` → `sum(last_7d) / min(7, actual_days_present)`. Cuts false `fading_100pct` alerts from 58/98 (60%) to ~0. | HIGH | 15 min | `runtime/intelligence/trend_tracker.py:208-210` |
| **6** | **Retire or harden `news_trends_double` rule.** Either drop the rule, raise min ticker length to ≥3, or gate it on news authority tier ≥ LLM_SINGLE. The rule's signal-to-noise is currently ~0. | MEDIUM | 20 min | `runtime/cross_reference/__init__.py:365-397` |
| **7** | **Race-fix `risk_governor` NAV=$0 → halt band.** Mirror the loop's `nav < 100` guard inside `risk_governor.check_proposed_trade` or pass the loop's normalized band as override. | MEDIUM | 1 hr | `runtime/portfolio/risk_governor.py`, `loop.py:367-371` |
| **8** | **Fix `options_flow.metadata.ticker` enrichment.** Title prefix has the ticker; just regex-extract it on persist so EntityClusterer can bucket. Boost the cross_source factor on 4,116 rows of UW data. | MEDIUM | 30 min | `runtime/awarebot/agent.py` `_scan_options_flow` area |
| **9** | **Drop the phantom `youtube_council` from `_INTEL_SOURCES`.** Either rename YTC emissions to use that source, or remove from whitelist. The phantom makes convergence-rule counting under-attribute YTC's role. | LOW | 10 min | `runtime/cross_reference/__init__.py:49` |
| **10** | **Add observability to silent fallbacks.** Counters for `EntityClusterer` failures, `AuthorityLearner` blend failures, `BERTopic` load attempts, `_PROMO_MARKERS` per-marker hit rate, `_persist_dedup_cache` drop rate. All currently debug-log-only. | LOW | 1-2 hr | `runtime/awarebot/agent.py` various |

**The single must-fix-this-week**: #1. Without it, the entire TRADERAGENT exists only as a sophisticated logging system. With it, items 2-10 become triage on a system that's actually operating.
