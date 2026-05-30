# NCL Free-Resource Deep Dive — by Lane

**Companion to**: `COST_AUDIT_2026-05-30.md` (LLM cost cuts) and `COST_AUDIT_OSS_ADDENDUM_2026-05-30.md` (DeepSeek/Groq/Ollama).
**This doc covers**: free data sources, open-source libraries, and self-hostable services NCL can adopt to *extend capabilities* across all 5 lanes — Portfolio / Intel / Calendar / Journal / Memory.

Every recommendation is verified current as of May 2026 (sources at end). Anything labeled "Skip" is either gutted in 2026 or replaced by a better free option.

---

## The frame

NCL's iOS bottom tabs are the 5 lanes. Each lane has a mandate and a pain point. Free resources do one of three things:

1. **Fill data gaps** the lane mandate calls for but the code doesn't have a source for
2. **Cut paid-LLM spend** by moving routine reasoning to local OSS models
3. **Improve quality** with better embeddings / rerankers / KG queries that cost nothing at runtime

The deliverable below maps each free resource to a specific NCL pain point + effort estimate + projected gain.

---

## 1. PORTFOLIO LANE

**Mandate**: paper account, auto-trader activity, scanner picks, rotation.
**Pain points today**:
- Crypto source DEAD since 2026-05-19 (CoinGecko rate-limited)
- Earnings calendar flaky (yfinance fallback after Finnhub key)
- Options surface shows premium splits + call/put ratio but **no aggregated Greeks**
- Auto-trader graduation gate computes SQN/expectancy/profit-factor MANUALLY
- AWAREBOT scorer runs Sonnet on news headlines (~$2-5/day Anthropic burn)
- No factor decomposition on paper trades (can't explain *why* GOAT is winning)

### Portfolio recommendations

**[HIGH-1] CCXT — restore the dead crypto signal**
- **Free, no key, Apache 2.0**, 107 exchange integrations, actively funded.
- Wire `fetch_ticker` + `fetch_ohlcv` against Binance + Coinbase + Kraken public endpoints (no auth needed).
- Replaces the broken `runtime/awarebot/crypto_*.py` path.
- **Effort: ~2 hours**. **Benefit: restores ~6 days of dark crypto signal, zero ongoing cost.**

**[HIGH-2] SEC EDGAR full-text + financial-statements API**
- **Free, no key**, 10 req/sec hard cap. `User-Agent: name email@addr` header required.
- Two surfaces:
  - `data.sec.gov` — XBRL company facts (10-Q/10-K line items)
  - `efts.sec.gov` — full-text search across all filings, including Form 4 (insider trades)
- Replaces the flaky yfinance earnings-calendar fallback (Wave 14G P19 was a band-aid).
- Adds **insider-buying alerts** to PORTFOLIO lane — Form 4 within 48h of close for held tickers.
- **Effort: ~4 hours**. **Benefit: durable earnings calendar + new insider-trade signal, free forever.**

**[HIGH-3] Marketaux — ticker-tagged news API**
- 100 req/day free, no card, **commercial-use allowed** (NewsAPI.org forbids it).
- 5,000 sources, 200K tagged entities, native sentiment + ticker-scoping built in.
- 100/day = 4 calls/hour, perfectly fits AWAREBOT's cadence if scoped to watchlist tickers.
- **Effort: ~3 hours**. **Benefit: drops NewsAPI dependency; entity-tagged headlines straight into the AWAREBOT pipeline.**

**[HIGH-4] FinBERT2 local — cut Anthropic spend on news scoring**
- 2026 release, +9-12% over leading LLMs on 5 finance classification benchmarks.
- Runs on CPU fast; M1 Ultra MPS → thousands of tokens/sec.
- Replaces every `_call_anthropic` in the AWAREBOT scorer's `actionability` + `context relevance` factors for text-heavy signals.
- **Effort: ~1 day** (install + benchmark + wire). **Benefit: directly addresses the Wave 14X-2 billing-blocker; ~$2-5/day Anthropic savings.**

**[MED-5] Tradier sandbox — options Greeks**
- Free sandbox account, no brokerage required.
- Options chain with delta/gamma/theta/vega/rho/phi via `?greeks=true`.
- Sandbox is delayed/simulated; live brokerage account upgrades the same endpoints to real-time without code change.
- **Effort: ~6 hours**. **Benefit: aggregated portfolio Greeks in iOS OPTIONS sub-tab; enables delta-neutral sizing for auto-trader friction profile.**

**[MED-6] quantstats + riskfolio-lib — replace manual graduation math**
- `quantstats` — Sharpe/Sortino/Calmar/SQN/expectancy + 30+ metrics + HTML tearsheet. Drop-in.
- `riskfolio-lib` — risk budgeting + factor exposure, active Feb 2026 release for Python 3.13/3.14.
- Replaces the manual math in `runtime/portfolio/auto_trader/graduation_gate.py`.
- **Effort: ~4 hours**. **Benefit: ~30 metrics + free HTML tearsheet per strategy graduation review; better quality than current code.**

**[MED-7] Kenneth French Data Library — Fama-French factor returns**
- Static CSV/ZIP downloads from Dartmouth, no rate limit, free forever.
- Use `pandas-datareader.famafrench` or `getFamaFrenchFactors` helper.
- Lets the Wave 14K SHAP attribution explain *which factors* a strategy is loading on.
- **Effort: ~3 hours**. **Benefit: factor decomposition per held position; surfaces "GOAT is just loading on SMB+momentum" insight.**

**[LOW-8] BLS + World Bank macro feeds — extra independent votes for cycle phase**
- Free, no keys for World Bank; 500/day for BLS.
- Wave 14I `cycle_phase.py` uses FRED-only inputs; adding BLS CPI/NFP/JOLTS as independent confirmation reduces single-source risk.
- **Effort: ~3 hours**. **Benefit: cycle classifier robustness without changing logic.**

**[LOW-9] pandas-ta-classic — drop-in TA library swap**
- Original `pandas-ta` went inactive 2024; `pandas-ta-classic` (xgboosted fork) is the maintained successor.
- One-line import change if you're using pandas-ta anywhere.
- **Effort: 15 min**. **Benefit: forward-compatible TA without rewriting.**

**Skip list for Portfolio**:
- Alpha Vantage (free tier gutted to 25/day, news sentiment now paid-only)
- Polygon.io (5 req/min on free, no real-time options, paid starts $199/mo)
- vectorbt (open-source frozen, paid PRO is the active fork)

---

## 2. INTEL LANE

**Mandate**: YTC, Reddit, X (paused), Predictions, Polymarket, cross-ref. Source priority: YTC #1, Reddit #2, X #3 (paused), Markets+Polymarket merged at #5.
**Pain points today**:
- X scanner DEAD since 2026-05-19 ($30/day spend gone — but also signal gone)
- Reddit fixed today (Wave 14AD RSS fallback) — surfaces good content with all 54 subs
- Theme convergence in Cross-Reference Engine uses **5 HARDCODED keyword clusters** (rate_policy/ai_capex/energy_supply/crypto_macro/geopolitical)
- AWAREBOT sentiment scoring runs Sonnet on every headline
- No live geopolitical-event source

### Intel recommendations

**[CRITICAL-1] Bluesky AT Protocol Jetstream — direct X replacement**
- Free, no auth, public firehose via 4 official Jetstream instances (`jetstream1.us-east.bsky.network` etc.)
- Lightweight JSON over WebSocket — slots into AWAREBOT pipeline cleanly.
- Bluesky is where the finance/macro/crypto crowd defected to from X in 2024-25 (Krugman, Cullen Roche, prediction-market folks).
- Filter `app.bsky.feed.post` events by watchlist tickers + keywords.
- **Effort: ~1 day** (WS handler + scorer wiring). **Benefit: restores the dead X social signal, zero ongoing cost. THE highest-leverage Intel change available.**

**[HIGH-2] Manifold Markets public API — prediction-market cross-confirm**
- No key required for read, 500 req/min per IP.
- Higher-velocity, more numerous markets than Polymarket on long-tail topics (AI capabilities, science, niche geopolitics).
- Direct fit for the Wave 14X-Y Cross-Reference Engine — adds a *third* prediction-market source alongside Polymarket.
- **Effort: ~3 hours** (Polymarket collector pattern). **Benefit: HOT-3× cross-source promotions are much more likely with 3 prediction-market sources than 1.**

**[HIGH-3] Kalshi public API — CFTC-regulated event markets**
- Free, no auth for market data. Real-money, CFTC-regulated.
- Best-in-class for US-macro contracts (CPI prints, Fed decisions, election odds, jobs).
- Deeper liquidity than Polymarket on US-specific economic events → higher signal-to-noise.
- **Effort: ~3 hours**. **Benefit: adds the most reliable prediction-market source for macro-anchored convergence.**

**[HIGH-4] miniflux self-hosted RSS aggregator**
- Single Go binary, runs on the same Mac Studio under launchd. SQLite backend.
- Configure 200-500 finance/macro/crypto/tech/geopolitics/AI feeds, expose JSON API on Tailscale.
- NCL polls **one well-built aggregator** instead of fanning out hundreds of per-feed fetches every loop.
- **Effort: ~4 hours** (launchd plist + initial OPML import). **Benefit: massive reliability + cadence improvement on the RSS surface; quietly the highest-leverage Intel-side change.**

**[HIGH-5] FinBERT2 + twitter-roberta-sentiment — local sentiment pipeline**
- FinBERT2 for headlines (Marketaux + RSS), twitter-roberta for social (Bluesky + Mastodon).
- Replaces all ad-hoc Sonnet sentiment scoring in AWAREBOT.
- Pairs directly with Portfolio recommendation #4 (FinBERT2 install is shared).
- **Effort: ~1 day** (shared with Portfolio #4). **Benefit: zero-cost sentiment scoring at vastly higher throughput than LLM calls.**

**[MED-6] BERTopic — dynamic theme clustering**
- Replaces the **5 hardcoded keyword sets** in the Cross-Reference Engine's theme convergence rule.
- BERTopic combines sentence-transformers + UMAP + HDBSCAN + c-TF-IDF to *learn* themes from the AWAREBOT stream over a rolling 7d window.
- Catches emerging themes (e.g. "stablecoin yield" or "GPU export controls") that hand-curated keyword lists miss.
- **Effort: ~1.5 days** (requires sentence-transformers install first — already in audit Phase 2). **Benefit: emergent theme detection; Cross-Reference engine becomes adaptive rather than static.**

**[MED-7] GDELT 2.0 — geopolitical event signal**
- Updates every 15 min, free, no key.
- Two access paths: direct file downloads (NGrams 3.0 datafile) or BigQuery (free 1TB/month quota with partitioned reads).
- Event records tag actor-action-target with CAMEO codes — perfect for the AWAREBOT situational-relevance factor (the new 7th factor from Wave 14X-Y Phase 1B-4).
- **Effort: ~1 day** (BigQuery service account + ingestion mapper). **Benefit: geopolitical signal NCL is missing entirely; cross-source confirm for energy/defense/EM tickers.**

**[MED-8] Mastodon public timeline APIs**
- Free, per-IP 7,500 req/5min unauthenticated. Instance-picking: `mastodon.social`, `infosec.exchange` (breach/CVE intel that moves stocks).
- Lower SNR for finance than Bluesky — use as a secondary social source, not primary.
- **Effort: ~4 hours** (HTTP poll, no special protocol). **Benefit: independent confirmation source for Bluesky signals.**

**[LOW-9] Telegram public-channel scrape**
- `t.me/s/<channel>` returns the last 100 posts via plain HTML, no API key, no auth.
- Public crypto + alt-finance channels (whale-trackers, options-flow alerts) live primarily on Telegram.
- Curate 5-10 high-signal public channels.
- **Effort: ~2 hours**. **Benefit: niche crypto/alt-finance signal that doesn't reach Reddit or Bluesky.**

**Skip list for Intel**:
- Pushshift / pullpush.io (intermittent; use only as historical backfill via arctic-shift HF dumps)
- NewsAPI.org / GNews (worse than Marketaux on every axis: terms, entity tagging, freshness)
- MediaCloud (bureaucratic, search-oriented not bulk, low priority)
- OpenSanctions (narrow; do later if needed)

---

## 3. CALENDAR LANE

**Mandate**: today's events, lunar, market events, watchlist to-dos. NATRIX directive 2026-05-30: include Ticketmaster + general news, not just financial.
**Pain points today**:
- City coverage limited to Ticketmaster + curated JSONL; no direct city-data feed for Edmonton/Calgary even though both publish events on open-data portals
- FOMC calendar is **hardcoded** in `runtime/calendar/events.py` (yearly maintenance burden)
- No big-money positioning signal in the Rotation Tracker (Wave 14I)
- Latin American cities (Panama City / San Salvador / Montevideo / Asuncion / Oaxaca) have no machine-readable event feeds

### Calendar recommendations

**[CRITICAL-1] CFTC Commitments of Traders — big-money positioning into rotation**
- Public reporting portal at `publicreporting.cftc.gov`, Socrata API conventions, JSON, no key.
- Weekly drop Fridays 3:30 PM ET with Tuesday data.
- Plugs directly into `runtime/intelligence/rotation_tracker.py` — adds an Open-Interest / Net-Speculative-Positioning signal alongside JdK RS-Ratio + yield-curve.
- This is the **single highest-leverage Calendar addition** — fixes a known gap in the Wave 14I rotation engine.
- **Effort: ~4 hours**. **Benefit: missing big-money positioning signal in the rotation tracker; one of the few inputs the engine currently lacks.**

**[HIGH-2] Edmonton + Calgary open-data portals**
- `data.edmonton.ca` and `data.calgary.ca` — both Socrata-backed, free, no key.
- Edmonton has a dedicated **Public Events Calendar Listings** dataset (SODA queryable).
- Wire directly into `runtime/calendar/local_events.py` alongside the Ticketmaster pull.
- **Effort: ~3 hours**. **Benefit: native events feed for NATRIX's two home cities; richer Calendar lane content.**

**[HIGH-3] Federal Reserve RSS feeds**
- `federalreserve.gov/feeds/feeds.htm` — separate streams for speeches, FOMC press releases, statistical-release calendar.
- No key, no quota, no maintenance burden.
- Replaces the **hardcoded FOMC dates** in `runtime/calendar/events.py` (currently 2026-only).
- **Effort: ~2 hours**. **Benefit: self-updating Fed calendar; removes annual maintenance burden.**

**[MED-4] Open-Meteo extended endpoints (air quality, climate, marine, historical)**
- NCL already uses basic Open-Meteo forecast. Same 10K calls/day non-commercial tier; CC-BY 4.0 attribution.
- Air quality endpoint adds **UV index + pollen + PM2.5/PM10** — relevant for Edmonton's outdoor windows.
- Historical endpoint (ERA5 reanalysis hourly since 1940) lets you back-fill mood↔weather correlation in past journal entries.
- **Effort: ~3 hours**. **Benefit: richer ambient context in Calendar; mood-weather analytics in Journal/Memory bridge.**

**[MED-5] GDELT events for Calendar geopolitical**
- Already covered in Intel #7. Same data feed serves both surfaces — Intel surfaces it as signals; Calendar surfaces it as upcoming-event dates.
- **Effort: ~0 if Intel #7 done first**. **Benefit: shared data spans both lanes.**

**[MED-6] OpenStreetMap Overpass API**
- Free, public, no key. Per-slot rate limiting; use kumi.systems mirror for redundancy.
- "What's near me right now" for 7 cities — query `amenity=cafe|theatre|cinema|library|marketplace`.
- Persist per-city POI JSON, refresh weekly.
- **Effort: ~4 hours**. **Benefit: ambient context for Calendar (relevant for NATRIX's travel days).**

**[LOW-7] OECD release calendar — Finnhub-free fallback**
- SDMX REST API, free, no key.
- Today the Brief Prep `economic_calendar` block goes empty when Finnhub key is missing — OECD provides backstop.
- **Effort: ~3 hours**. **Benefit: economic calendar resilience.**

**Skip list for Calendar**:
- Eventbrite (public events killed Feb 2020, never returned)
- Meetup (migrated to paid GraphQL Feb 2025)
- Songkick (acquired by Suno late 2025, paid partnership only)
- SeatGeek (US-only data; weak for Edmonton/Calgary)
- NASA JPL Horizons / NASA Open APIs (Skyfield already covers the practical lunar need)

---

## 4. JOURNAL LANE

**Mandate**: morning quiz, today's focus, yesterday's lesson, posture. NATRIX's voice is source of truth.
**Pain points today**:
- No voice-journal path (NATRIX writes on iOS; no audio capture)
- ReflectionEngine produces text; **no spoken output** for ambient consumption
- Wisdom corpus is 50 static entries; rotates the same lines
- No CBT-grounded reframing prompts

### Journal recommendations

**[HIGH-1] WhisperX — voice journaling with diarization**
- BSD-2-Clause, actively maintained (v3.8.6 released May 25, 2026).
- Adds word-level timestamps + speaker diarization to Whisper.
- NCL is already running MLX-Whisper for transcription — WhisperX adds the diarization layer.
- Voice-journal entries: NATRIX records on iOS, NCL transcribes locally with speaker-tagged segments, pushes a structured `voice_journal` entry into the JournalStore.
- **Effort: ~1 day** (transcoder wiring + iOS audio upload endpoint). **Benefit: voice-journal lane that doesn't exist today; private, local-only, zero LLM cost.**

**[HIGH-2] Piper TTS — spoken brief playback**
- Maintained at `OHF-Voice/piper1-gpl` (Open Home Foundation). Local, ONNX, ~10× realtime on CPU.
- Pipe the AM Brief's 5-lane narrative through Piper, drop the .wav to `data/morning-brief-pro/2026-XX-XX.wav`, surface from iOS BriefLandingCard as a "Play" affordance.
- 5-10s render for 1,500 chars on the M1 Ultra.
- **Effort: ~6 hours** (render hook + iOS audio player). **Benefit: spoken brief — NATRIX listens during coffee instead of reading; the Brief becomes an ambient surface.**

**[MED-3] edge-tts — Piper fallback with higher-quality voices**
- Wraps Microsoft Edge's online TTS via undocumented protocol. No key, free, neural voices.
- Risk: depends on Microsoft not changing the protocol (occasional breakage, patched within days).
- Pair with Piper: edge-tts for normal use, Piper as offline fallback.
- **Effort: ~2 hours**. **Benefit: higher-fidelity voice for brief playback when online; offline fallback.**

**[MED-4] Stoic public-domain corpora — extend wisdom rotator**
- Marcus Aurelius (Meditations), Epictetus (Discourses + Enchiridion), Seneca — all on Project Gutenberg, fully public domain.
- Current 50-entry corpus is static; full text would let the wisdom rotator generate fresh quote pulls daily.
- **Effort: ~3 hours** (bulk download + per-book chunker). **Benefit: 50× more wisdom-rotation variety; no LLM cost.**

**[LOW-5] CBT corpora on Hugging Face — CBT-grounded reframing prompts**
- Three relevant datasets: `Psychotherapy-LLM/CBT-Bench`, `IINOVAII/therapy-conversations-combined`, DiaCBT.
- Licenses vary; some are research-only. License-check before bundling.
- Mine ~50 high-quality CBT reframing prompts; extend the current stoic-heavy daily-wisdom corpus.
- **Effort: ~4 hours** (license review + manual curation). **Benefit: CBT prompts for Weekly/Yearly Review wizards; more reflection-prompt variety.**

**Skip list for Journal**:
- Tesseract OCR (useless on handwriting; NCL has no printed-text journal path)
- TrOCR (defer until iOS adds handwritten-page photo upload — surface doesn't exist)
- Coqui XTTS v2 (Coqui shut down Dec 2025; Idiap fork's model is CPML/non-commercial only)
- LangChain/LlamaIndex journaling modules (weaker than NCL's existing memory stack)

---

## 5. MEMORY LANE

**Mandate**: pinned working context, top-salience memories, active themes. Substrate for permanent recall.
**Pain points today**:
- FusedRetriever stops at RRF — **no reranker** post-pass; relevance is whatever the fusion ranks first
- `contradicts_index.jsonl` is a 5MB-bounded grep file; queries are O(n) scans
- ChromaDB embeddings use the default model (English-only; LatAm content + multi-language YTC transcripts lose quality)
- M1 dedup runs every 6h with 500-unit sliding window; not real-time
- Knowledge Graph is NetworkX in-memory + JSONL persist; full reload on every boot; no Cypher query

### Memory recommendations

**[CRITICAL-1] BGE-reranker-v2-m3 — post-RRF rerank stage**
- The **single biggest quality lift** NCL can land this week. ~600M params, multilingual.
- Today FusedRetriever returns RRF rank-1; adding a reranker post-pass on top-50 → top-10 lifts retrieval quality 10-20% on SOTA benchmarks.
- Runs on M1 Ultra at estimated ~200-400 docs/sec — under the 1s budget for `/memory/search/fused`.
- Drop into `runtime/memory/retrieval/fusion.py` as a stage gated by `NCL_RERANKER_ENABLED`.
- **Effort: ~1 day**. **Benefit: massive quality lift in Memory Smart Search + chat-context assembly; $0 ongoing cost.**

**[HIGH-2] BGE-M3 — multilingual embedding model**
- 568M params, 100+ languages, 8K token context, MTEB ~62.6.
- Slightly bigger than nomic-embed-v1.5 (2.3GB vs 274MB) but higher quality on retrieval-heavy benchmarks.
- Latin American local-events pipeline pulls Spanish text; multi-language YTC transcripts arrive in various languages — multilingual matters.
- Re-embed `ncl_signals` and `ncl_episodic` collections with BGE-M3 over a weekend.
- **Effort: ~1 day** (download + reindex + dual-model collection tagging). **Benefit: better quality across LatAm + YTC surfaces.**

**[HIGH-3] Kuzu — embedded graph database**
- In-process, Cypher-compatible, native vector + FTS. Benchmarks **~18× faster than Neo4j** on ingest + n-hop pathfinding.
- Native NetworkX export — drops cleanly into NCL's existing KG code as a persistence upgrade.
- Cross-Reference Engine's theme-convergence rules become single Cypher queries instead of N×M Python scans.
- **Effort: ~1.5 days** (Kuzu setup + KG migration + Cypher rewrite of cross-reference rules). **Benefit: KG queries become a first-class feature; Cross-Reference engine becomes more powerful.**

**[HIGH-4] datasketch MinHashLSH — real-time dedup**
- NCL already uses SimHash. MinHashLSH gives **true LSH-bucketed near-dup detection** — O(1) lookup instead of pairwise compare.
- Rewrite the M1 dedup loop (`ncl-dedup-scan`, 500-unit sliding window every 6h) as a persistent MinHashLSH index.
- Dedup becomes **incremental** — each new unit is one hash + one bucket lookup vs scanning a window.
- **Effort: ~6 hours**. **Benefit: real-time dedup instead of 6h cadence; lower memory; less CPU.**

**[MED-5] Qdrant OR LanceDB — vector DB swap-out**
- Two paths, pick one:
  - **Qdrant** — separate process on port 6333, 3× ChromaDB throughput on 1M-vector benchmarks. Apache 2.0. Run under launchd.
  - **LanceDB** — embedded, no separate process. Arrow-columnar, NVMe-friendly, claims ~15ms query on 5M vectors.
- For NCL's scale (25K units) the throughput delta is academic — pick by deployment preference.
- Strong use case: replace `contradicts_index.jsonl` with a Qdrant/Lance collection where contradictions are stored with payload `{unit_id_a, unit_id_b, jaccard_score, resolved}` and queryable by payload-filter.
- **Effort: ~2 days** (bulk migration + dual-write transition + cutover). **Benefit: faster vector search; contradict-index becomes queryable; future-proofs growth past 100K units.**

**[MED-6] DSPy — chair prompt optimization**
- Stanford NLP, MIPROv2 optimizer. Hand-tunes prompts via metric-based search.
- Could plausibly squeeze another 10-20% quality from the Brief chair prompt against frozen labeled-good-vs-bad briefs.
- Cost: hours of one-shot optimization runs (uses LLM credits for the search itself).
- **Effort: ~2 days**. **Benefit: better brief chair output. Run AFTER the 5-lane structure stabilizes from NATRIX's mandate.**

**[LOW-7] Cognee — spike-eval only**
- Apache 2.0, builds a "living KG" from unstructured docs.
- Evaluate Cognee's KG-construction quality against NCL's current entity-extractor on a 1,000-doc sample of YTC reports.
- If Cognee's KG is meaningfully cleaner → lift the construction pipeline; don't adopt the rest of the framework.
- **Effort: ~1 day** (eval spike). **Benefit: data point; don't adopt unless eval shows clear quality win.**

**Skip list for Memory**:
- Microsoft GraphRAG (heavy; expects you to live inside its KG-construction pipeline; would tear out NCL's NetworkX + ACE reflection + Cross-Reference)
- LightRAG framework (same issue — read the paper, port the *dual-level retrieval* idea into FusedRetriever; skip the framework)
- Letta (MemGPT) runtime (would mean replacing NCL's whole memory stack)
- Mem0 (still Apache 2.0, but no meaningful upgrade over NCL's create_unit flow)
- Milvus Lite (lags behind cluster product; LanceDB is the cleaner embedded pick)
- Weaviate local (heavier than Qdrant; hybrid-search edge is marginal vs Qdrant + BGE-reranker)
- dedupe.py / recordlinkage (NCL at 14K units; overkill — datasketch MinHash is enough)
- GTE-base / GTE-large embeddings (BGE-M3 overtakes them on every benchmark NCL cares about)

---

## Cross-cutting recommendations

Three free additions that improve multiple lanes at once:

**[CROSS-1] FinBERT2 + twitter-roberta sentiment local pipeline**
- Improves Portfolio (replaces Sonnet in AWAREBOT scoring)
- Improves Intel (sentiment on Bluesky/Mastodon/RSS posts)
- Cost: ~$2-5/day Anthropic savings + zero-cost throughput at scale.

**[CROSS-2] sentence-transformers install**
- Activates 3 dormant subsystems already coded in NCL (quorum semantic clustering, late-chunking RAG, awarebot topic clustering)
- Required dependency for BERTopic (Intel #6) + BGE-reranker (Memory #1)
- ~150MB install, ~80MB model cache. **One pip install unlocks ~5 capabilities.**

**[CROSS-3] miniflux self-hosted**
- Improves Intel (RSS firehose)
- Improves Calendar (Fed RSS feeds, OECD release feeds, city open-data RSS where available)
- Improves Memory (consistent ingest cadence for indexing)
- One launchd plist, one OPML import, **lifts the entire ingest reliability surface**.

---

## Phased adoption roadmap

### Phase 1 — This week (zero risk, immediate wins)

| # | Lane | Item | Effort | Why first |
|---|------|------|--------|-----------|
| 1.1 | Intel | **Bluesky Jetstream** | 1 day | Restores dead X social signal |
| 1.2 | Intel | **miniflux self-hosted** | 4h | Lifts entire RSS reliability |
| 1.3 | Portfolio | **CCXT** | 2h | Restores dead crypto signal |
| 1.4 | Calendar | **CFTC COT** | 4h | Closes rotation-tracker gap |
| 1.5 | Memory | **BGE-reranker-v2-m3** | 1 day | Biggest quality lift available |
| 1.6 | Cross | **sentence-transformers install** | 30 min | Unlocks 5 downstream capabilities |

**Phase 1 net**: 6 features added in ~3 days of work. Zero ongoing cost. Closes the four biggest known capability gaps (X-dead, crypto-dead, rotation-incomplete, retrieval-unranked).

### Phase 2 — Next 1-2 weeks (medium effort)

| # | Lane | Item | Effort | Why |
|---|------|------|--------|-----|
| 2.1 | Cross | **FinBERT2 + twitter-roberta** | 1 day | Cuts $2-5/day Anthropic; faster sentiment |
| 2.2 | Portfolio | **SEC EDGAR** | 4h | Earnings calendar + insider trades |
| 2.3 | Portfolio | **Marketaux** | 3h | Ticker-tagged news |
| 2.4 | Intel | **Manifold + Kalshi APIs** | 6h | Prediction-market triangulation |
| 2.5 | Calendar | **Edmonton + Calgary open data** | 3h | NATRIX's home cities native |
| 2.6 | Calendar | **Fed RSS feeds** | 2h | Self-updating FOMC calendar |
| 2.7 | Journal | **Piper TTS** | 6h | Spoken brief playback |
| 2.8 | Memory | **BGE-M3 embeddings** | 1 day | Multilingual reindex |
| 2.9 | Memory | **datasketch MinHashLSH** | 6h | Real-time dedup |

**Phase 2 net**: 9 more features, ~1 week of work. Major capability lift; ~$2-5/day Anthropic savings.

### Phase 3 — When stabilized (architectural, optional)

| # | Lane | Item | Effort | Why |
|---|------|------|--------|-----|
| 3.1 | Intel | **GDELT 2.0** | 1 day | Geopolitical events |
| 3.2 | Intel | **BERTopic dynamic themes** | 1.5 days | Cross-Reference adapts |
| 3.3 | Journal | **WhisperX** | 1 day | Voice-journal lane |
| 3.4 | Portfolio | **Tradier sandbox Greeks** | 6h | Aggregated options Greeks |
| 3.5 | Portfolio | **quantstats + riskfolio** | 4h | Graduation gate upgrade |
| 3.6 | Memory | **Qdrant OR LanceDB** | 2 days | Vector DB swap |
| 3.7 | Memory | **Kuzu KG persistence** | 1.5 days | Cypher queries |
| 3.8 | Memory | **DSPy chair-prompt optimization** | 2 days | After 5-lane stabilization |

**Phase 3 net**: 8 architectural improvements. Defer until Phase 1+2 stabilize.

### What I'd ship FIRST if I had to pick one

**Bluesky Jetstream + miniflux + BGE-reranker-v2-m3** — 3 changes, ~2 days work, restores the dead X signal, lifts the entire RSS surface, and adds reranking to Memory search. All free forever.

---

## Combined savings impact (with the LLM cost audit)

The LLM cost audit projected $9.39/day → $2.44/day (74%) via DeepSeek + Ollama swaps. Adding **Phase 1+2 of this doc** (FinBERT2 local sentiment + Bluesky replacing X social need + GDELT replacing some geopolitical LLM calls):

| | Today | Cost-audit alone | + This addendum |
|---|---:|---:|---:|
| Anthropic | $6.81/day | $1.30 | **$0.90** (FinBERT2 takes sentiment scoring) |
| OpenAI | $0.87/day | $0.20 | $0.20 |
| Perplexity | $1.20/day | $0.30 | $0.30 |
| Google | $0.09/day | $0.05 | $0.05 |
| DeepSeek V3 | $0 | $0.30 | $0.30 |
| Groq Llama 3.3 | $0 | $0.10 | $0.10 |
| YTC bucket | $0.42/day | $0 | $0 |
| Free-tier APIs (Marketaux 100/day, Bluesky, CCXT, etc.) | n/a | n/a | $0 |
| Self-hosted (miniflux, Qdrant, Piper, FinBERT2 inference) | n/a | n/a | $0 |
| **TOTAL** | **$9.39/day** | **$2.25/day** (76% saved) | **$1.85/day** (80% saved) |

Hitting **80%+ daily-spend savings** is realistic once the cost audit + this doc's Phase 1+2 are shipped together. The cost cuts and the capability expansion are the same set of changes done two ways.

---

## Sources

### Portfolio + Intel research
- [SEC EDGAR APIs — Rate Limits & Best Practices](https://tldrfiling.com/blog/sec-edgar-api-rate-limits-best-practices)
- [SEC.gov | EDGAR Application Programming Interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Finnhub Rate Limit Docs](https://finnhub.io/docs/api/rate-limit)
- [Tradier Options Chains](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains)
- [CCXT GitHub](https://github.com/ccxt/ccxt)
- [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
- [Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)
- [QuantStats](https://github.com/ranaroussi/quantstats)
- [pandas-ta-classic fork](https://github.com/xgboosted/pandas-ta-classic)
- [FinGPT GitHub](https://github.com/AI4Finance-Foundation/FinGPT)
- [FinBERT2 paper](https://arxiv.org/pdf/2506.06335)
- [Bluesky Jetstream — Blog](https://docs.bsky.app/blog/jetstream)
- [Bluesky Firehose docs](https://docs.bsky.app/docs/advanced-guides/firehose)
- [Mastodon Rate Limits](https://docs.joinmastodon.org/api/rate-limits/)
- [Manifold API docs](https://docs.manifold.markets/api)
- [Kalshi API docs](https://docs.kalshi.com/welcome)
- [GDELT Project data](https://www.gdeltproject.org/data.html)
- [cardiffnlp twitter-roberta-base-sentiment-latest](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest)
- [Marketaux Pricing](https://www.marketaux.com/pricing)
- [FreshRSS vs Miniflux 2026](https://ossalt.com/guides/freshrss-vs-miniflux-2026)
- [Telegram public channel scrape 2026](https://dev.to/sami_8858131362756585e4f4/how-to-scrape-telegram-channels-in-2026-without-api-keys-or-phone-numbers-195)

### Calendar + Journal + Memory research
- [Eventbrite Platform API](https://www.eventbrite.com/platform/api)
- [Meetup GraphQL API](https://www.meetup.com/graphql/)
- [NOAA api.weather.gov](https://www.weather.gov/documentation)
- [Open-Meteo Features](https://open-meteo.com/en/features)
- [Overpass API rate limiting](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [Edmonton Open Data — Events](https://data.edmonton.ca/Events/Public-Events-Calendar-Listings/64u3-c7bh)
- [Open Calgary](https://data.calgary.ca/)
- [CFTC public reporting](https://publicreporting.cftc.gov/stories/s/Commitments-of-Traders/r4w3-av2u/)
- [Federal Reserve RSS Feeds](https://www.federalreserve.gov/feeds/feeds.htm)
- [WhisperX GitHub](https://github.com/m-bain/whisperX)
- [Piper TTS (OHF fork)](https://github.com/OHF-Voice/piper1-gpl)
- [edge-tts](https://github.com/rany2/edge-tts)
- [CBT-Bench HF dataset](https://huggingface.co/datasets/Psychotherapy-LLM/CBT-Bench)
- [Discourses of Epictetus, Project Gutenberg](https://www.gutenberg.org/ebooks/10661)
- [Qdrant vs Chroma 2026](https://4xxi.com/articles/vector-database-comparison/)
- [LanceDB](https://www.lancedb.com/)
- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [BGE-reranker-v2-m3 model card](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [ms-marco MiniLM cross-encoder](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag)
- [LightRAG](https://lightrag.github.io/)
- [Letta GitHub](https://github.com/letta-ai/letta)
- [Cognee GitHub](https://github.com/topoteretes/cognee)
- [Kuzu GitHub](https://github.com/kuzudb/kuzu)
- [datasketch MinHash walkthrough](https://dzone.com/articles/minhash-lsh-implementation-walkthrough)
- [DSPy GitHub](https://github.com/stanfordnlp/dspy)
