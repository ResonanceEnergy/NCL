# Awarebot Intel Pipeline Audit — 2026-05-29

**Scope:** `runtime/awarebot/*.py`, `runtime/intelligence/{brief_prep,brief_council,brief_presenter,rotation_tracker,style_ratios,cycle_phase}.py`, `runtime/api/routers/intel/__init__.py`; live brain at `100.72.223.123:8800`.
**Snapshot:** brain uptime 6 min, `agent_signals.jsonl` = 18,668 rows (16M, plus .1=51M, .2=50M), `units.jsonl` = 24,770 rows, `latest_brief.json` 15h stale.

---

## 1. Sources inventory

8 declared, 6 active. `DEFAULT_SCAN_INTERVAL=300s` per `_scan_loop`; 10K-row dedup via `Signal.fingerprint()=SHA256(source:title[:100]:content[:200])`; per-source token-bucket limiters (`RATE_LIMITS`). 24h total = 7,544 signals.

| Source | Status | 24h | Watch input | Downstream notes |
|---|---|---|---|---|
| **reddit** | LIVE, 10 rpm | **3,394** | 6 search + 55 subs (T1=10 + T2=16 every cycle; T3=29 rotated 5/cycle via `_tier3_offset`) | context deques + AsyncMemoryWriter (8,248 lifetime mem units); seeds News fan-out |
| **options_flow** (UW) | LIVE, 10 rpm | **2,385** | none | same; also feeds `/portfolio/options-flow` independently |
| **google_trends** | LIVE, 5 rpm | **669** | none | same + brief |
| **youtube** | LIVE, 30 rpm + council-report ingest (48h, top-5/report) | **372** + insights | 6 queries | same; council insights softened to r=0.50/a≤0.65/auth=0.65 (Wave 14C) |
| **polymarket** | LIVE, 20 rpm | **316** | none | same + `brief_prep.collect_polymarket_leading()` reads `_recent_signals` directly |
| **news** | LIVE, 15 rpm, ≤5 queries/cycle | **294** | **NONE OF ITS OWN** — fans out top-3 from each watch-source ⇒ structural cross-source inflation | same |
| **city_events** | LIVE, 1h per-city throttle (7 cities) | **71 sum** | calendar.local_events | same + city_scanner writes its own memory copy = duplicate write |
| **x_twitter** | **DISABLED** (`X_SCANNER_ENABLED=false`, 402) | 0 | 8 queries still in config | — |
| **crypto/coingecko** | **DISABLED** (commented out) | 0 | — | — |
| `council_youtube`/`council_unknown` | LIVE disk-read (`intelligence-scan/council-reports/*.json`) | n/a | n/a | counted twice in `_stats["signals_by_source"]` (as `youtube` AND `council_youtube`) |

`/intelligence/stats source_count=8` post-restart: leaked from prior-session in-memory `_stats` counters.

---

## 2. Scoring + tier routing

**6-factor composite** (`compute_composite_score`, sum=1.0):

| Factor | W | Implementation |
|---|---|---|
| context_relevance | 30% | `compute_relevance_bm25` blended 70/30 with scanner.relevance, then blended **50/50** with mandate/working-ctx keyword match — halving BM25's effective contribution |
| freshness | 20% | HN-gravity `1/(age_h+2)^1.8 * 10`; ~1.0 first hour, ~0.15 by 6h |
| cross_source | 15% | `EntityClusterer` (entity+sector graph, 6h window, 500-cluster LRU) → falls back to token-Jaccard over `_context_7d`. `1-exp(-0.6*n_sources)` saturating |
| source_confidence | 15% | base map (polymarket 0.85 → reddit 0.45 → x 0.40) + engagement 60/40 + Reddit upvote/comment log boost + verified-X/follower boost; 70/30 blended with `AuthorityLearner` posterior |
| actionability | 10% | scanner floor → ≥0.6+conf when `direction≠neutral & conf>0.6` → ≥0.7 when `|change_pct|>10` |
| novelty | 10% | SimHash 64-bit + exp decay `1-exp(-0.1*hrs_since_near_dupe)`, floor 0.05, 0.9 if novel |

**Tier classification:** CRITICAL ≥0.75 → top10+24h+7d + memory@85 + working_ctx inject + push + council_flags write. HIGH ≥0.55 → 24h+7d + memory@65 + working_ctx. MEDIUM ≥0.30 → 24h+7d + memory@45 (Wave 14B promoted to 24h). LOW <0.30 dropped. **0.30-0.55 ambiguous zone** → Ollama DeepSeek (cap 10 calls/cycle).

**`route_to_tiers` for iOS:** single-pass exclusive, pulls from `_context_top10/24h/7d`, caps 4/source/tier + 2× overflow. MMR diversification when `NCL_MMR_ENABLED=true`. Age windows: Focused ≥0.75 & <4h, Micro ≥0.50 & <24h, Macro ≥0.30 + narrative sources OR >24h. Live `/context/focused` shows 10 slots = YT + Polymarket alternating.

---

## 3. Signal data flow trace

Polymarket "Will the price of Bitcoin be above $74,000 on May 28?" (sig `900a01ee-9f55-494a-a114-e3fcbcfa52d3`):

1. **Ingest** — `_collect_polymarket()` (20 rpm bucket) → `Signal.from_intel_signal()`. `metadata.lifecycle_status="leading"` (Wave 14G P17-D).
2. **Dedup** — fingerprint check against 10K `_seen_set`. Daily settlement events ship fresh body (`YES=20.1%, NO=80.0%`) so fingerprint flips daily → same contract counted as new each day.
3. **Score** — relevance ~0.50, freshness ~0.85, cross-source ~0.40-0.70, authority 0.85, actionability 0.6 (bearish, conf 0.658), novelty 0.9. **Composite=0.741 → HIGH**.
4. **Route** — `_route_high()`: appends `_context_24h+_context_7d`, fires `_store_to_memory(importance=65)` via AsyncMemoryWriter, fires `_inject_working_context()`.
5. **Memory** — `units.jsonl` row, `source=awarebot:polymarket`, `memory_type=signal`, `tier_for_source→SCANNER(20)`. Same contract persisted **54×** in units.jsonl.
6. **Brief** — `IntelligenceEngine.generate_morning_brief()` re-scores via `IntelSignal.importance_score()` (separate 0-100 scale). Lands in `latest_brief.json.top_signals` (importance 71.5).
7. **iOS surfaces (4):** `/intelligence/signals/top` (brief subset, imp 71.5), `/context/focused` (Awarebot deque, composite 0.741), `/intelligence/digest` (brief again), `/memory/search/fused?q=bitcoin` (all 54 historical units). **Same item, 4 endpoints, 3 scoring scales.**

**Disk:** `grep -c "Bitcoin be above \$74"` → 64 in `agent_signals.jsonl`, 54 in `units.jsonl`.

---

## 4. Volume + freshness right now

**Live `/intelligence/stats`** (post-restart): `signal_count=0`, `signals_routed=0`, `last_scan_at=null`. `by_source` leaked from prior session: `news 75, youtube 60, unusual_whales 47, city_events 32, polymarket 23, council_youtube 20, council_unknown 20, google_trends 10`.

**On-disk truth (`agent_signals.jsonl`, last 24h = 7,544 of 18,668 lifetime):**

| Source | 24h vol | Lifetime in file | Last |
|---|---|---|---|
| reddit | 3,394 (45%) | 8,248 | 1.4h |
| options_flow | 2,385 (32%) | 4,562 | 1.0h |
| google_trends | 669 | 1,174 | 0.4h |
| youtube | 372 | 1,928 | 0.4h |
| polymarket | 316 | 693 | 0.7h |
| news | 294 | 1,144 | 0.6h |
| city_events (sum) | 71 | 315 | 1.0h |
| unknown | 43 | 604 | 21.2h (stale) |

**Score distribution lifetime:** CRITICAL ≥0.75 = 1,069 (5.7%); **HIGH 0.55-0.75 = 11,235 (60.2%)**; MEDIUM = 6,364 (34.1%); LOW = 0 persisted.

**Stale flags:** `latest_brief.json` ts = 2026-05-28T11:52Z, now 03:18Z → **~15.5h stale**. iOS Intel Brief, `/intelligence/digest`, `/intelligence/signals/top` all serve yesterday's brief. `night_watch_status.freshness=stale`. `unknown` source last 21h ago. `intelligence_signals_list` endpoint accepts `source=` query param but **ignores it** — always returns brief top_signals.

---

## 5. Overlap / competing-for-space analysis

**5a. Awarebot tiers vs WorkingContext salience — orthogonal in practice, redundant in code.** Two separate scorers on overlapping input. Awarebot scores 6-factor composite, optimized for recency+cross-source; DailyContextWindow scores `0.25*recency + 0.35*importance + 0.25*relevance + 0.15*authority`. Live `today.json` = **50 of 50 items are `narrative_thread:$TICKER`** aggregations from the `ncl-narrative-threads` 6h loop. Zero awarebot signals survived — threads aggregate 4,000+ units each and dominate importance. Awarebot's `_inject_working_context()` on every HIGH/CRITICAL is dead work — salience evicts them immediately.

**5b. Focus tab IS Awarebot's input config, mis-positioned in UI.** `/focus/queries` and `/focus/subreddits` are CRUD on `runtime/autonomous/watch_queries.json`, which `Awarebot._load_watch_queries()` reads. iOS positions Focus as a tab beside Predictions/Brief/YTC, so it reads like another source when it's the search terms feeding all sources.

**5c. Same item double-counted across Intel cache and Memory store.** Polymarket BTC question = 64× in `agent_signals.jsonl` + 54× in `units.jsonl`. `awarebot:*` units = **21,747 of 24,770 = 88% of MemoryStore**. `memory_type=signal` = 80% of units. City-event units double-written (city_scanner has its own AsyncWriter handle on top of Awarebot's route).

**5d. iOS hits both `/intelligence/*` and `/memory/*` for same data — yes.** 6 of 9 Intel sub-tabs (Brief/Focus/YTC/Reddit/X/News/Markets) plus 4 of 4 Memory sub-tabs read slices of the same Awarebot pool, projected differently. No surface tells the user "this is the same item you saw on another tab." `/intelligence/digest` (Wave 14A) was built to be the unified read — iOS still doesn't consume it ("adopts in 14B" — queued, per FirstStrike CLAUDE.md).

**5e. brief_prep adds a third reader.** `brief_prep.collect_headlines` + `collect_polymarket_leading` reach directly into `brain._awarebot._recent_signals` — a third independent reader alongside `route_to_tiers` and `_store_to_memory`.

---

## 6. Quality

**Discrimination is poor.** HIGH (0.55–0.75) absorbs 60% of persisted signals ⇒ ~940 HIGH/day, un-actionable by definition. The 50/50 BM25↔keyword blend halves BM25; watchlist ~70 unique tokens so most market-flavored text gets a match. Cross-source (15%) saturates by 5 sources, but `news` is a re-broadcast of Reddit+YouTube+X+Trends queries, so every topical hit auto-inflates cross-source by design.

**Examples:** *Good:* `polymarket 0.741 | Bitcoin > $80K on May 27?` (directional, dated). *Good:* `news 0.690 | Average Guys Outsmarting Wall Street on Prediction Markets — nytimes.com`. *Borderline:* `google_trends 0.659 | denzel washington` (single search spike, no trade impl — scored HIGH because authority 0.8 + novelty 0.9 + freshness 0.85). *Noise HIGH:* `city_events:edmonton 0.650 | Girls On The Run 5K`, `city_events:calgary 0.662 | Calgary Transit Hiring event` (community events scored as intel because ticketmaster authority=0.6). *Reddit chat:* `reddit 0.511 MEDIUM | recent CS grad looking for a job`.

**Actionable ratio:** of 7,544 24h signals, fewer than ~30 are framed enough to back a decision (polymarket leading + movers, options_flow >$1M premium, named-ticker DD) — **<0.5%**. The brief pipeline (Wave 14H council+critic) correctly distills to 6 trade ideas/day, so output quality is OK; the ingest is 99.5% noise carrying weight in cross-source + KG + narrative-thread pipelines.

---

## 7. Top 3 issues

**1. Same signal triple-persisted across 6 representations — HIGH (architectural).** Every routed signal lands in: (a) three Awarebot context deques, (b) `agent_signals.jsonl` (.1+.2 rotation = 117 MB combined), (c) AsyncMemoryWriter → `units.jsonl` + ChromaDB + BM25 + KG, (d) `latest_brief.json` subset, (e) narrative-threads aggregation, (f) night-watch dedup. BTC Polymarket question = 64× in agent_signals + 54× in units. Memory grew 9.7K → 24.7K units in one week, 88% awarebot-sourced. **Fix:** persist to memory only on CRITICAL OR cross_source ≥ 2; stop `_inject_working_context()` entirely (salience evicts anyway); cap MEDIUM persistence at 7-day rolling retention; have the 3 surfaces declare which view they are so iOS can dedupe.

**2. Intel tab fragments same data across 9 sub-tabs, with brief 15h stale and no live single read — HIGH (UX × data).** `/intelligence/digest` exists for this but iOS doesn't consume it. Brief tab shows yesterday's 11:52 UTC brief. Focus is mis-positioned as an output lane when it's input config CRUD. Source sub-tabs (Reddit/X/YT/Trends/News) re-display data Awarebot already ingested without surfacing the score or overlap. **Fix:** pin `/intelligence/digest` as Intel→RIGHT NOW; move Focus into Settings/Watch; collapse source sub-tabs into "Drill down" under digest; show one badge per signal ("rank N in Focused" / "cited in Brief" / "memory thread $TICKER") so the user sees one item = one underlying signal.

**3. 6-factor compresses at HIGH from News fan-out + over-trusted authorities — MEDIUM (quality).** 60% of persisted signals HIGH ⇒ band is meaningless. Causes: (a) `news` has no own queries, fans top-3 from each watch-source, structurally inflates cross-source on every topical hit; (b) google_trends authority 0.8 + high novelty + freshness fires `denzel washington`-class signals into HIGH; (c) city_events ticketmaster authority 0.6 → community events score as intel; (d) 50/50 BM25↔keyword blend halves the only factor that genuinely discriminates relevance. **Fix:** drop `news`-as-derivative; lower google_trends authority 0.8→0.4 (popularity, not editorial); remove city_events from Awarebot — they belong in Calendar; raise HIGH threshold 0.55→0.65 to thin band ~40%; undo the 50/50 BM25 dilution (keyword match should boost, not replace half of, BM25).

---

**Bottom line:** the "competing for space" concern is correct but the four systems aren't *competing* — they're **stacked**: Focus = Awarebot's input config, Awarebot = scorer + tier projector, its output persists into memory, memory feeds working_context, working_context feeds councils/brief, brief feeds iOS Intel. Cost is volume and ambiguity: 7.5K signals/24h with 60% HIGH; 88% of MemoryStore is Awarebot-sourced; brief is 15h stale; iOS Intel surfaces the same items across 9 lenses without telling the user. Triage News fan-out + city_events + google_trends (the noise carriers), surface `/intelligence/digest` in iOS, tighten persistence to CRITICAL + cross-confirmed — and "overloaded" becomes "one signal pool, three honest projections."
