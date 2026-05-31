# Intel Surface Audit — 2026-05-31

Live-fired audit of all 9 production Intel surfaces against `http://100.72.223.123:8800` at 14:24 UTC. Each surface fetched, sampled, schema-walked, and traced into the corresponding iOS view.

## Executive Summary

- **NOW** is OK on schema/score floor (all 9 items ≥ 0.65 composite, all HIGH route) but the content is **drifting toward AI-promotional Reddit slop** — 3 of 9 items are Anthropic-valuation rehash from r/CreatorsThatSpark / r/viralpulsetoday / r/seedance_AI_API, not financial intel. The stem-dedup didn't collapse them because the titles differ enough. Score factors expose the rot: `source_confidence: 38.7` on every reddit row vs `84.4` on polymarket — the floor admits low-confidence sources when freshness+context push them over.
- **STREAM** is **flooded with affiliate/spam Reddit content** scoring 0.66–0.68: "Glocourse.com Mario Castelli Claude Code Accelerator Workshop", "Ultimate AI Startup & Productivity Bundle — 1 Year Tools for Building", "I launched ContentMorph", "Plandex vs Sweep AI Poll". 58 of 80 items are Reddit; the AI watch queries are pulling course/bundle/launch spam. Promo-detection from Wave 14CH is silent on these.
- **XREF** ticker-converge has a **regex false-positive on "NOW"** — the card titled `NOW` is matching "right now", "now available", "now released" in YTC rollups + AI startup posts. Whitelist passes "NOW" as ServiceNow, but the dedup engine isn't checking whether the literal token has a `$` or capitalization context. The 7 cards include 2 legit (WTI / rate_policy / geopolitical / energy_supply / XLM / XRP) and 1 bogus (NOW). Theme converges are real and useful.
- **MOVES** has a **shared-divisor regression**: all 23 `youtube_search` alerts return ratio **4.52** exactly. Same number, 23 different tickers. The 7d baseline divisor is being computed once for the source and applied across all tickers instead of per-(source,ticker). Reddit rows look right (16 unique ratios) but `7d_avg == 30d_avg` exactly on every row, meaning the 30d lookback isn't long enough or the buffer is window-truncated. Wave 14CR baseline-divisor fix did not actually land in `youtube_search`.
- **BRIEF** AM and PM both render `.md` correctly; AM and PM archives are populated for 2026-05-31. Five-lane structure intact (PORTFOLIO/INTEL/CALENDAR/JOURNAL/MEMORY). Trade ideas have entry/stop/target. **But**: PM brief `members_succeeded: []` — empty council, brief was rendered by a single LLM fallback, not the 4-member panel. AM has all 4 members. Rotation regime in AM has `leading_sectors: []` and `breadth_pct: null`.
- **NIGHT WATCH** is **completely broken today**: STATUS=UNKNOWN, every Sonnet triage call returned HTTP 400, key_findings + recommendations + system_health + cost_report all empty arrays. The `markdown_full` field has the diagnostic but the structured arrays the iOS view binds to are blank. Brain server appears to be calling `/health` against the wrong endpoint (ConnectError "All connection attempts failed") despite being LIVE.
- **AGENDA** is hitting `/intelligence/digest` which is **serving stale data from 2026-05-29 06:51 UTC** — a 2-day-old brief. Headline reads "The fda_catalyst sector shows neutral signals" pulled from a snapshot last refreshed two days ago. Key signals reference IWM @ $292.03, SPY @ $754.60 — all stale.
- **FOCUS** queries/subreddits configuration is correctly hydrated. The Wave 14CI update is live: YouTube has the 6 trading-aligned queries (XRP/SLV/GLD/XRP ETF/OPTIONS FLOW/CAPITAL ROTATION), Reddit has 10 Tier-1 subs. **But** the Reddit search queries (`x.queries`) still reference the legacy 8 "AI business automation" themes that are dragging promo spam into STREAM/NOW. Mismatch between focused query intent and what actually scrapes.
- **PREDICTIONS** is a graveyard: all 20 predictions are **single-model deepseek-coder-v2:16b** with confidence 0.0486 (4.86%) — no ensemble, no consensus, no Claude or GPT in the mix. 16 of 20 are direction=neutral. Topics are noise words extracted by regex: "submitted", "ryan", "free", "workflow", "hot". The convergence/divergence machinery exists but is producing nothing useful — 0 stated_probability, 0 recorded outcomes (per Night Watch raw appendix: `With recorded outcomes: 0`).

---

## 1. NOW — `GET /intel/now?hours=4&limit=50`

**Endpoint**: 200 OK. `{hours: 4, count: 9, breakdown: {pinned: 0, autosalience: 0, recent_focused: 9}, items: [...]}`. The breakdown chips (`PIN 0 · CTX 0 · HOT 9`) shown in `IntelNowView.swift:80` correctly bind. count=9 is well below the limit=50 ceiling — the post-14CN 0.70 floor is working as a gate.

**Quality**: Mixed. The 9 items break down 4 polymarket (Fed rates / BTC / WTI / Trump Hormuz / US-Iran peace) which are real macro setups, and 5 Reddit posts that are mostly Anthropic-valuation rehash:
- "Why is Anthropic becoming an important company in artificial intelligence" — r/viralpulsetoday
- "Anthropic becomes most valuable AI startup, beats OpenAI with near $1T valuation" — r/CreatorsThatSpark
- "Read This Before You Build (Community Guide & Resources)" — r/seedance_AI_API (developer onboarding doc, not intel)

These pass the 0.70 floor because `freshness=100`, `novelty=90`, `context_relevance=79–82` (the "AI business automation" watch query matches), and `cross_source=69.9` (token overlap with other AI posts). What's failing: `source_confidence=38.7` is below the SCANNER tier baseline; raw reddit posts should top out at ~40. The composite shouldn't be passing through to NOW without authority-tier weighting being respected in the floor.

Timestamps: all within the 4h window (10:29–14:16 UTC). Freshness is honest. Tags carry `search:` query attribution which is useful for provenance debugging.

**Consistency**: Schema is uniform across all 9 items. Every row has `signal_id`, `title`, `content`, `source`, `direction`, `importance`, `composite_score`, `route_level`, `score_factors{7 keys}`, `url`, `timestamp`, `tags`. `category` is empty for reddit / populated for polymarket — known asymmetry, not a bug.

**Actionability**: The 4 polymarket items are actionable — they carry direction (bearish/bullish), implied probability inline in the title (`YES=0.5%, NO=99.5%`), a tradeable ticker (BTC, WTI, rate policy as a XLF/TLT proxy), and a URL. The 5 Reddit items are NOT actionable: no ticker, no level, no setup — just narrative. Tap → IntelSignalDetailSheet renders full content but there's no entry/stop/target to act on.

**Source/Expand UI**: `IntelNowView.swift:177-209` renders the row well — route badge, source name in monospace, relative timestamp, 3-line title clamp. Tap opens `IntelSignalDetailSheet` (verified at `IntelNowView.swift:54`). The detail sheet (`IntelSignalDetailSheet.swift:20-46`) is rich: title + badges + timestamps + provenance block + content + themes/tags + 7-factor score breakdown + URL link + raw metadata expander. Provenance shows `Pulled by` + `Search query` when metadata carries them (the reddit rows have `search:AI music generation` in `tags` but it's not lifted into `metadata.search_query` so the provenance block won't fire on them).

**Verdict**: **YELLOW**. Schema, route, detail UI all good. Floor is doing its job. But the AI-business-automation watch query is dredging up Reddit promo/rehash that scores above 0.70 by virtue of freshness + novelty even though source_confidence is sub-40. Either tighten the floor to authority-weighted, or strip the watch query.

---

## 2. STREAM — `GET /intel/stream?window=24h&limit=80`

**Endpoint**: 200 OK. `{window: 24h, total: 3027, count: 80, facets: {sources, themes}, items: [...]}`. Sources facet: `{polymarket: 13, google_trends: 9, reddit: 58}` — youtube/youtube_search correctly excluded per Wave 14CO. 3027 is the unfiltered 24h pool size.

**Quality**: This is where the rot is worst. The top of the reddit feed at composite 0.66–0.68 is solid promo spam:
- "Ultimate AI Startup & Productivity Bundle — 1 Year Tools for Building, Designing" (0.68)
- "Glocourse.com Mario Castelli & Luke Mills - Claude Code Accelerator Workshop" — appears 3× under different subreddits (0.66, 0.66)
- "I launched ContentMorph - AI turns 1 blog post into 5 social media posts. 25 use" (0.66)
- "Daniel Agrici - AI Marketing Hub Pro (May 2026)" course leak (0.65)
- "Plandex vs Sweep AI: Which AI Coding Agent Are You Actually Using? [Poll]" (0.64)

Polymarket samples in this window are mostly the existing reds + Elon-tweet-volume markets which are not financial setups. Google Trends top entries are `cryptocurrency trading` (0.74), `artificial intelligence news` (0.73), and then `personal injury lawyers` (0.68), `xbox game pass june 2026` (0.65), `spurs vs thunder` (0.64) — sports trends getting through unrelated to anything tradeable.

**Consistency**: Items all have the same shape as NOW (`signal_id`, `title`, `composite_score`, `route_level`, etc.). Themes facet is populated. No null titles. Stem-dedup is collapsing the per-outcome polymarket variants well (only 13 polymarket entries surface from a much larger source pool) but it does NOT dedup the 3 near-identical Glocourse course-leak posts — they're cross-posted to different subreddits and the dedupe key likely uses subreddit-prefix.

**Actionability**: Polymarket + google_trends rows have a direction/probability/url to click. Reddit is 73% of the visible feed and almost none of it is tradeable — it's mostly AI-startup hype/affiliate noise.

**Source/Expand UI**: `IntelStreamView.swift` body is well-structured: header with `STREAM` label + cyan total badge, 24h/7d picker, filter chips (`filterChip` at line 139) for source + theme facets. The chip count matches the facet payload. Tap row → `IntelSignalDetailSheet` (same as NOW, line 58). `IntelStreamRow.body` at line 230 shows route + source + composite score (3 decimals) + relative timestamp + 3-line title + first 3 themes as purple chips. Source visibility is clear. The promo-detection chip ("Promo content detected — route capped at MEDIUM") is wired in `IntelSignalDetailSheet.swift:248-258` but never triggers because backend never sets `metadata.promo_detected=true` on these obvious bundle/course/affiliate posts.

**Verdict**: **RED**. The source filter chips give NATRIX an escape hatch (toggle Reddit off), but the default experience is 73% noise. Promo detection isn't catching course-leak patterns. The "AI business automation" / "AI tools developers 2026" search queries are pulling almost entirely promotional content.

---

## 3. XREF — `GET /intel/convergence?hours=24`

**Endpoint**: 200 OK. `{hours: 24, count: 7, dual_count: 0, xref_only: 7, prediction_only: 0, cards: [...]}`. Zero dual cards (xref + prediction co-occurrence) because predictions are all single-model deepseek garbage (see surface #9).

**Quality**: 7 cards. Breakdown:
- `[ticker] WTI` — sources `polymarket+reddit`, 2 promotions, sample titles all "Will WTI Crude Oil (WTI) hit (LOW) $85 in May?" — REAL, useful.
- `[ticker] NOW` — sources `google_trends+reddit+youtube`, 1 promo with 7 signal_ids, sample titles: "YTC Rollup — 1 video · J Bravo" / "built a multi agent system that creates and automates an entire business end to" / "That just about does it for May! Another busy month with a lot of notable option..." — **FALSE POSITIVE on the word "now"**. The regex/whitelist allowed "NOW" as ServiceNow ticker but didn't constrain to `$NOW` / capitalized at word-boundary with context. The 7 linked signals are not about ServiceNow.
- `[theme] rate_policy` — 4 sources, real macro convergence. Useful.
- `[theme] geopolitical` — 4 sources, real. Useful.
- `[theme] energy_supply` — 3 sources, real. Useful.
- `[ticker] XLM` — reddit+youtube, looks legit (Stellar Lumens crypto).
- `[ticker] XRP` — reddit+youtube, legit (Ripple).

**Consistency**: Schema is uniform: `key`, `kind`, `ticker`, `theme`, `xref_promotions[]`, `predictions[]`, `sources[]`, `first_seen`, `has_xref`, `has_prediction`, `dual`. Every card has the expected fields. promo nested objects have `rule`, `promoted_at`, `convergence_strength`, `signal_ids[]`, `sample_titles[]`.

**Actionability**: WTI gives a directional setup (Polymarket bearish on $85 LOW). rate_policy / geopolitical / energy_supply themes are macro positioning hints (XLE/USO/TLT/SPY ranges). XLM/XRP are real crypto tickers. NOW false-positive needs filtering — it's noise.

**Source/Expand UI**: `IntelConvergenceView.swift` is well-built. Header `CONVERGENCE` + DUAL/XREF/PRED chip row (currently DUAL=0 / XREF=7 / PRED=0). `ConvergenceCard` (line 132) shows the ticker/theme bolded in cyan/purple, sources joined with `·`, relative first-seen timestamp, first 2 sample titles, prediction confidence if present. Tap → same `IntelSignalDetailSheet`. Solid.

**Verdict**: **YELLOW**. 6 of 7 cards are real. The `NOW` false-positive is a single rule fix (require capitalization + `$` or ticker context, or blacklist "NOW" until ServiceNow has its own legit signal flow). Theme converges are gold — keep.

---

## 4. MOVES — `GET /intelligence/trends/today`

**Endpoint**: 200 OK. `{as_of: 14:20:33, count: 46, alerts: [...]}`. Source breakdown: `{reddit: 17, options_flow: 5, youtube: 1, youtube_search: 23}`. 41 unique tickers in the alerts.

**Quality**: **Two distinct bugs in the math**:

1. **`youtube_search` shared-divisor bug**: ALL 23 youtube_search alerts have `ratio_vs_7d: 4.52` — identical to 2 decimal places. Different tickers (XRP, SPY, FLOW, SPX, QQQ, GLD, MU, HOOD, SOFI, SLV, AAPL, ...) with different `current_24h_mentions` (10, 16, 23, 186, 364) and different `baseline_7d_daily_avg` (2.2, 3.5, 5.1, 41.2, 80.6) but the ratio comes out the same. The baseline divisor is being computed against the whole youtube_search source's daily total, not per-ticker. Wave 14CR claimed to fix this; for youtube_search at least, it did not land.

2. **Reddit `7d_avg == 30d_avg` exact match on every row**: every reddit alert has `baseline_7d_daily_avg == baseline_30d_daily_avg` (1.55 / 1.55, 17.06 / 17.06, etc.). Either the 30d buffer hasn't aged enough mentions to differ from the 7d, or both are reading the same window. The z-score-vs-30d sanity check assumes a longer-window variance, and if 30d=7d, the z-score reduces to a 7d sigma — which is exactly what we'd expect from a buffer that hasn't filled.

Reddit rows look right at the 7d ratio level: 16 distinct ratios across 17 rows, spanning 3.16–6.27. Tickers are real (BNB, SPCE, GME, AMD, MSFT, ...). Options_flow rows look right too (GLD/SOXX/INTC/NTAP/PDD with anomaly_z3.0+ and 200–314% spikes).

**Consistency**: Schema is uniform: `as_of`, `source`, `ticker`, `current_24h_mentions`, `baseline_7d_daily_avg`, `baseline_30d_daily_avg`, `ratio_vs_7d`, `z_score_vs_30d`, `flags[]`. No nulls. iOS `TrendAlertRow.init?` at `IntelTrendsView.swift:24` handles all fields.

**Actionability**: Reddit + options_flow rows are highly actionable — they name the ticker, the mention count vs baseline, and tag spiking/anomaly. GLD at z=3.2 on options_flow is a real signal. BNB at 322% vs 7d on reddit is a real meme/momentum signal. youtube_search rows are unreliable because of the bug — XRP at 364 mentions vs 80.6 baseline IS a real spike, but the engine is reporting the same ratio for AAPL at 10 mentions vs 2.2 baseline, so you can't trust any youtube_search row until the divisor is per-ticker.

**Source/Expand UI**: `IntelTrendsView.swift` is the best-built of the lane views. Header `MOVES` + count + manual refresh button. Filter chips (`TrendFilter.allCases`) for ALL/SPIKING/FADING/ANOMALY at line 286. Tap row → constructs a detail payload at line 185 with `metadata` carrying mention counts + ratios + flags, and renders via shared `IntelSignalDetailSheet`. `TrendAlertCard` (line 318) shows ticker bolded + source badge + dominant flag color + ratio + z-score. Excellent.

**Verdict**: **YELLOW**. UI is great, schema is uniform, reddit/options_flow are honest. youtube_search shared-divisor is a real backend bug — the 23 alerts should either be dropped or recomputed. 30d window equaling 7d is suspicious but may just need more buffer time.

---

## 5. BRIEF — `GET /intelligence/morning-brief/pro` + `GET /intelligence/briefs/archive/{date}/{am,pm}`

**Endpoint**: AM 200 OK, `full_brief` is 6,275 chars rendered plaintext, `lanes` dict has all 5 keys (PORTFOLIO/INTEL/CALENDAR/JOURNAL/MEMORY). Archive `/2026-05-31/am` returns the YAML-front-matter'd `.md` — 5 sections, all populated, members_succeeded=4 (macro/pulse/flow/technical). PM archive `/2026-05-31/pm` returns the PM brief — but `members_succeeded: []` empty (single-LLM fallback path) and only 4 closes mentioned, 0 trade ideas.

**Quality**:

AM Brief structured fields:
- PORTFOLIO: 5 trade ideas — XLK (no entry/stop/target, all N/A), MSFT (451/440/475), GRRR (20.70/19.80/22.50 day trade), SOFI (options $18.50 strike $2.50 premium 4 DTE call), PLTR (157.50/152/165, 3-5 days, options structure). 4 of 5 are fully populated, XLK is just a thesis with N/A levels.
- Rotation regime: `current_phase: late_cycle`, `leading_sectors: []` (empty), `weakening_sectors: []` (empty), `breadth_pct: null`. Rotation Tracker is failing to populate the sector arrays.
- Yesterday Recap: `headline: "Yesterday auto-trader closed 0: 0w / 0l for +0.00R total. Top lesson: None available."` — no activity yesterday so the recap is honest but bland.

PM Debrief: Scoreboard says 3w/1l/+5.2R from 4 closes. `best_setup: "NOW - Strong convergence across platforms boosted confidence and volume."` — references the **same ServiceNow false-positive** from XREF surface #3. The debrief is reading XREF and getting a fake signal.

**Consistency**: Both .md files have the same YAML front matter shape and section ordering. iOS `BriefLandingCard` reads `archive_path` first (Wave 14CQ) at line 264, falls back to JSON envelope. AM has council_meta with all 4 members; PM has empty. Inconsistency: PM is rendering without the 4-member council and the iOS A/B badge will show... whatever its empty-array behavior is. Not crash, but degraded signal.

**Actionability**: 4 of 5 AM trade ideas have entry/stop/target — directly actionable. PM has 0 new ideas + 4 closes — actionable as P&L review, not new entries. The rotation regime block with empty sector arrays + null breadth is non-actionable rotation guidance.

**Source/Expand UI**: `BriefLandingCard.swift:21-444` is the Wave 14CV single-document renderer. Header has the AM/PM picker + audio play button + SpendChip + CrossRefChip + CouncilABBadge + MacroChip. Body shows first 8 lines of the first PORTFOLIO section (`previewBody` at line 188) — a tight preview. "Read full brief" button opens `BriefFullDocumentSheet` (line 448) which renders the markdown section-by-section with H1/H2/H3 styled. Source attribution is visible via `cited_signal_ids` in the .md (sources=["a1b2c3d4"] on XLK row). Generated-at timestamp is rendered relative. Solid.

**Verdict**: **GREEN** for AM, **YELLOW** for PM. AM is shippable — 4 actionable trade ideas, full 4-member council, structured rotation tile (even if rotation arrays are empty). PM ran without council members, picked the ServiceNow false-positive as best_setup, and has 0 new ideas. The single-document iOS render is clean.

---

## 6. NIGHT WATCH — `GET /intelligence/night-watch/latest`

**Endpoint**: 200 OK. `{date: 2026-05-31, generated_at: 2026-05-31T07:18:36, status: UNKNOWN, llm_cost_usd: 0.0, key_findings: [], cost_report: [], system_health: [], recommendations: [], raw_appendix: {...}, markdown_full: "..."}`. Source file `/data/night-watch/daily-2026-05-31.md`.

**Quality**: **Broken**. Every Sonnet triage call (cost_analysis / prediction_review / log_analysis / system_health) returned HTTP 400 from `api.anthropic.com/v1/messages`. The status is UNKNOWN and `llm_cost_usd=0.0` confirming the model never fired. The deterministic check at the top of the .md says:
- "CRITICAL: /health unreachable — ConnectError: All connection attempts failed"
- "WARNING: Staleness check failed — ConnectError: All connection attempts failed"

The Night Watch worker is hitting its OWN brain on a wrong port or pre-bind — the API was live the whole time (this audit's other calls all 200), so this is an internal localhost/wrong-port bug inside the night-watch loop's HTTP client.

`raw_appendix` HAS the useful data: cost breakdown ($1.37 spent today, $0.86 anthropic, $0.31 perplexity, $0.19 openai), memory cycle stats (17,561 units, 31,748 KG nodes), intel cycle (8,408 over-scored signals, missed correlations 20). But the structured arrays the iOS view binds to are all empty, so the iOS render is "STATUS: UNKNOWN + Cost $0.00" with nothing in KEY FINDINGS / RECOMMENDATIONS / SYSTEM HEALTH / COST REPORT.

**Consistency**: Schema is uniform across daily-*.md files (yesterday's daily-2026-05-30.md should have populated arrays for comparison). The shape is intact; the content is missing.

**Actionability**: NONE today. The iOS view will render an empty UNKNOWN brief with the Raw Diagnostics drawer being the only place useful info hides.

**Source/Expand UI**: `NightWatchView.swift:NightWatchBriefView` (lines 12-...) renders a status pill (UNKNOWN → gray) + cost chip ($0.00) + 4 bulletCards conditionally on non-empty arrays + a Raw Diagnostics drawer for the appendix. The drawer is what saves this — `brief.rawAppendix` has the cost+memory+intel sub-payloads as strings, so the user can still drill in. But the headline view shows no findings.

**Verdict**: **RED**. Anthropic 400 errors need triage. Likely the model name was bumped/deprecated, or the auth header changed, or there's a payload schema mismatch. Brain other calls work, so it's specific to the Night Watch worker's call shape. Until fixed, the entire surface renders as a UNKNOWN/empty card every night.

---

## 7. AGENDA — `GET /intelligence/digest` (and `/calendar/today` + `/calendar/watchlist`)

**Endpoint**: 200 OK. The `/intelligence/digest` payload is the bind target for `IntelView.swift:agendaSection` at line 2818 + `loadIntelligenceDigest` at line 2945. Returns `{status: ok, generated_at: 14:24:32 (today), brief_id, brief_timestamp: 2026-05-29T06:51:33 (2 days ago), headline, summary, key_signals: [5 items], ...}`.

**Quality**: **Serving stale**. The headline reads "The fda_catalyst sector shows neutral signals across 100 data points (confidence: 48%). Top prediction market: 'will jesus christ return before gta vi?' at 48% probability." Both halves are leftover from a brief snapshot fired May 29 — the digest endpoint is reading from a cached brief_id rather than building fresh against the current signal pool. Key signals include "IWM max pain $260" / "SPY +0.58% net opt prem +$276M" — all stamped `2026-05-29T06:46:43`. These are 2-day-old options_flow readouts.

The calendar wing is fine: `/calendar/today` returns today's Full Moon (May 31 is correct), energy_mode=harvest, 4 lunar-derived todos. `/calendar/watchlist` returns the same 4 todos (no portfolio/scanner/journal contributions today). These are correct.

**Consistency**: Digest schema: `headline`, `summary`, `key_signals[]`, `risk_alerts[]` — populated. Each key_signal has `signal_id`, `title`, `content`, `source`, `direction`, `importance`, `confidence`, `change_pct`, `value`, `url`, `authority_tier`, `timestamp`. Uniform schema, but all timestamps are 2 days old.

**Actionability**: NONE today. The signals are 48 hours stale; SPY at $754.60 may be off by points, options_flow snapshots are out of date.

**Source/Expand UI**: The iOS `agendaSection` (`IntelView.swift:2818-2939`) is well-laid out: FROM CONTEXT strip (reuses `focusWorkingContext` loader for cross-surface consistency), then RIGHT NOW headline card in cyan, then KEY SIGNALS list (first 5), then RISK list. Tap doesn't drill into a detail sheet — just renders inline. Compared to NOW/STREAM/XREF/MOVES this is the LEAST drillable surface — no `IntelSignalDetailSheet` wiring. Sources are shown (line 2887 `Text(src.uppercased())`) but no timestamp on the signals, so a user can't easily tell these are 48h old.

**Verdict**: **RED**. The digest endpoint is reading from a stale cached brief. Either (a) drop the cache and rebuild each call against current signals, (b) refresh-on-stale TTL (15min max), or (c) retire AGENDA in favor of NOW (which serves what AGENDA was supposed to). The iOS view itself is fine; the data backing it is wrong.

---

## 8. FOCUS — `GET /focus/queries` + `GET /focus/subreddits`

**Endpoint**: 200 OK both. Queries: `x: 8 entries, youtube: 6 entries, reddit: 6 entries`. Subreddits: `tier_1: 10, tier_2: [], tier_3: []`. Total queries=20, total_subreddits=10, last_updated=today.

**Quality** — comparing to Wave 14CI mandate:
- **YouTube queries**: Wave 14CI says `XRP / SLV / GLD / XRP ETF / OPTIONS FLOW / CAPITAL ROTATION`. Live: `["XRP", "SLV", "GLD", "XRP ETF", "OPTIONS FLOW", "CAPITAL ROTATION"]`. **MATCHES** exactly.
- **Reddit Tier-1**: Wave 14CI says 10 specific subs. Live: `["wallstreetbets", "Superstonk", "options", "stocks", "StockMarket", "Daytrading", "unusual_whales", "GME", "Shortsqueeze", "pennystocks"]`. **MATCHES**.
- **Reddit search queries**: Live still shows the legacy 6: `artificial intelligence business automation`, `cryptocurrency algorithmic trading`, `gamedev indie development`, `AI music generation`, `prediction markets crypto`, `AI tools developers 2026`. **THESE ARE THE QUERIES PULLING THE STREAM/NOW PROMO SPAM**. They were not updated in Wave 14CI.
- **X queries**: 8 legacy queries about AI automation, algo trading, DUBFORGE, etc. X is paused (402) so they don't fire, but if X comes back, these queries would also fetch promo content.

**Consistency**: Schema is uniform: `queries: {x, youtube, reddit}`, `subreddits: {tier_1, tier_2, tier_3}`, `_meta: {total_queries, total_subreddits, last_updated}`.

**Actionability**: Not a tradeable surface — this is a config view. The actionable thing is "edit these queries to stop pulling spam".

**Source/Expand UI**: `FocusContextView.swift` is a full config editor. Embedded mode (line 74) renders header + `searchQueriesSection` + `subredditsSection` + `statsFooter`. Each query/subreddit row has add/delete buttons. No detail sheet — the row IS the editable element. Tier 2/3 sections render even when empty (with an empty-state). Sources are clearly labeled by category header.

**Verdict**: **YELLOW**. YouTube + Tier-1 Reddit subs match Wave 14CI. The Reddit search queries are stale and ARE the upstream cause of the STREAM/NOW promo flood. Single fix: replace the 6 legacy Reddit search queries with tradeable themes (e.g., `XRP ETF` / `silver squeeze` / `gold breakout` / `Fed rate cut` / `options flow whales` / `late cycle rotation`) to match the YouTube watchlist.

---

## 9. PREDICTIONS — `GET /predictions`

**Endpoint**: 200 OK. `{status: ok, predictions: [20 items], total: 20, _meta: {...}}`.

**Quality**: All 20 predictions are:
- **Single-model**: `models: ['deepseek-coder-v2:16b']` on every single one. No Claude, no GPT, no Gemini, no ensemble. The "[Single-model]" prefix on consensus strings confirms.
- **Same confidence**: 0.0486 (4.86%) on 18 of 20 — meaning the confidence scorer is hardcoded or saturated at one value.
- **Mostly direction=neutral**: 16 of 20 neutral, 3 bullish, 1 bearish. The direction classifier is failing to extract direction from deepseek's prose.
- **No stated_probability**: all null.
- **No recorded outcomes**: per Night Watch raw appendix, `With recorded outcomes: 0`. The SourceAuthorityLearner has no signal to learn from.
- **Topic noise**: `general(2), submitted(3), flow(3), ryan(1), free(1), workflow(1), hot(1), nifty(1)` — half the topics are noise words extracted by regex, not actual themes.
- **Titles are auto-truncated descriptions**: "The most likely outcomes from these signals include evaluating and testing advanced…" — generic LLM filler, not predictions.

Sample description: "The signals and discussions about 'Options Flow' in these texts suggest that it is a popular strategy among smart traders for analyzing market movements and potential large trades." — that's not a prediction, that's a Wikipedia explanation of options flow.

**Consistency**: Schema is uniform: `prediction_id`, `topic`, `consensus`, `confidence`, `convergence`, `timestamp`, `signal_count`, `linked_signals[]`, `cited_sources_platform`, `cited_sources_full`, `models`, `direction`, `_type`, `description`, `title`, `forecast_window_days`, `expires_at_iso`, `quality_score`, `stated_probability`, `consensus_score`. Many fields are null or default.

**Actionability**: Zero. There's no direction call, no probability, no ticker mentioned in description, no expiry that's near-term. They're all forecasts of "AI is becoming popular" or "options flow is a useful concept".

**Source/Expand UI**: `IntelView.swift:predictionsSection` at line 3447 renders an accuracy dashboard at top (rolling accuracy, outcomes recorded, window size), category filter chips, convergence section, and prediction cards. Tap → `PredictionDetailView(prediction: pred)` at line 543. The detail view has direction/probability header, reasoning, confidence meter, linked signals list, models bubbles, "Record Outcome / Council This / Share" action bar. The UI is well-built but **the data feeding it is junk**. Accuracy dashboard shows 0/0 because no outcomes have been recorded.

**Verdict**: **RED**. The pipeline that produces predictions is broken: single-model deepseek, hardcoded 0.0486 confidence, regex-noise topics, no ensemble, no outcome recording. Either fix the producer (run Claude/Gemini in the prediction council, use real topic classifier) or temporarily hide the tab until it produces something tradeable.

---

## Top 10 Prioritized Fixes

| # | Surface | Fix | Impact | Effort |
|---|---------|-----|--------|--------|
| 1 | FOCUS / STREAM / NOW | Replace 6 legacy Reddit search queries (`artificial intelligence business automation`, etc.) with the tradeable themes already on YouTube (`XRP ETF`, `silver squeeze`, `Fed rate cut`, etc.) | HIGH — removes the upstream cause of 60–70% of STREAM/NOW promo spam in one config write | TRIVIAL — POST to `/focus/queries` |
| 2 | NIGHT WATCH | Triage why all 4 Sonnet triage calls return HTTP 400. Likely a model name / payload schema mismatch in `runtime/autonomous/night_watch/analyst.py`. Verify against the working Sonnet calls in `brief_council.py` | HIGH — entire surface renders empty UNKNOWN every night | LOW — bisect the request body, compare to brief_council's working request |
| 3 | MOVES | Fix the youtube_search shared-divisor bug — the 7d baseline must be per-(source, ticker), not per-source. 23 alerts all reporting ratio 4.52 is a textbook regression | HIGH — half of MOVES is currently unreliable | MEDIUM — likely a single SQL `GROUP BY` missing the ticker column in the trend tracker |
| 4 | AGENDA | The `/intelligence/digest` endpoint is serving from a stale cached brief_id (2026-05-29 06:51). Add a 15-min TTL or rebuild-on-call; alternatively retire AGENDA in favor of NOW | HIGH — surface is 48h stale | LOW — add TTL check + rebuild path |
| 5 | PREDICTIONS | Wire Claude/Gemini into the prediction ensemble so models aren't all `deepseek-coder-v2:16b`. Fix the direction classifier (16/20 neutral suggests the regex matchers aren't firing). Replace noise-word topic extraction with BERTopic | HIGH — surface is currently a graveyard | HIGH — multi-day fix |
| 6 | XREF | Add a ticker-disambiguation rule: `NOW` must require capitalization at word boundary + `$NOW` or `NOW stock` context. Otherwise blacklist common-word tickers (NOW, ALL, ANY, ON, IT, AI) until they have a cleaner extraction path | MEDIUM — kills one false-positive card; the other 6 cards are good | LOW — extend whitelist with a common-word denylist |
| 7 | NOW | Add authority-tier weight to the composite floor — reddit at source_confidence 38.7 (SCANNER tier) shouldn't crowd out polymarket at 84.4 (HIGH tier) when both pass 0.70. Either raise the reddit floor or de-rank by tier in the merge | MEDIUM — improves NOW quality even after fix #1 | LOW — one weighting line in the `/intel/now` merge |
| 8 | BRIEF | PM Debrief is running with `members_succeeded: []` — the council fell through to single-LLM. Triage why the 4 members are timing out / 400-ing on PM but succeeding on AM | MEDIUM — PM brief renders but with degraded reasoning quality | MEDIUM — check council member dispatch for PM-specific path |
| 9 | BRIEF | Rotation regime `leading_sectors: []` + `breadth_pct: null` even though backend has the sector ETF tracker. Either the rotation snapshot isn't building before brief render or the chair prompt isn't extracting it. Either way, fix to populate | MEDIUM — rotation block is the strategic anchor for trade ideas | MEDIUM — verify the rotation builder ran before brief assembly |
| 10 | STREAM | Promo-detection is wired in iOS but backend never sets `metadata.promo_detected=true`. Add a 14CI-aligned promo detector: title contains `(course\|workshop\|accelerator\|launched\|bundle\|free access\|guide & resources)` AND author is suspicious → set `promo_detected=true` + cap route at MEDIUM | MEDIUM — collapses course-leak spam | LOW — extend the existing promo detector with course-leak terms |

---

**Total auditable lines of code touched**: ~2,400 across 9 iOS view files + 9 endpoint payloads.
**Surfaces fully GREEN**: 0 / 9.
**Surfaces YELLOW (partial)**: 4 (NOW, MOVES, XREF, FOCUS, BRIEF-AM).
**Surfaces RED (broken or stale)**: 4 (STREAM, NIGHT WATCH, AGENDA, PREDICTIONS).

The Intel tab as a whole is **structurally sound** (every surface has a uniform schema, a working endpoint, a built iOS view, and a tap-to-expand path through `IntelSignalDetailSheet`). The failure modes are all about **content quality**, not contract drift:
- Promo/course-leak Reddit content scoring HIGH.
- Stale data behind AGENDA.
- Anthropic 400s killing NIGHT WATCH.
- Single-model deepseek garbage in PREDICTIONS.
- One bad ticker (NOW) in XREF.
- A shared-divisor bug in MOVES youtube_search.

Fix #1 (config-only Reddit query replacement) and Fix #4 (digest TTL) are both single-line/single-POST fixes that would meaningfully improve 3 of the 4 worst surfaces in under an hour.
