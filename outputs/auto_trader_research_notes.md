# Autonomous Trading Agent — Research Notes (2024-2026 Practice)

**Compiled**: 2026-05-27 for NCL Wave 14K auto-trader upgrade planning. Paper-trading only ($36K NAV, max 8 opens/day, 2/tick, 5% risk/trade, R:R ≥ 1.5). Strategies in scope: GOAT (trend), BRAVO (swing), pairs stat-arb, mean reversion, PEAD, factor, whale flow, crypto carry, Polymarket Kelly.

The reader already has: Beta-Bernoulli Thompson-sampled strategy bandit, Page-Hinkley drift detector, SHAP-flavored attribution, multi-criteria graduation gate, friction profile, risk governor (heat caps + drawdown throttle), per-trade reasoning chain capture. This document is the input to the next architecture wave.

---

## (a) Topic-by-topic findings

### 1. Idea generation & filtering (signal fusion, dedup, correlation-aware selection)

The consensus among serious shops (Fidelity's "Fusion Alpha", AQR-style multi-signal, Citadel sleeve construction) is to **treat signals as a portfolio problem, not a winner-takes-all problem**. You take N independent sleeves, each with a measurable Information Ratio, and combine them in proportion to IR / variance after cleaning the correlation matrix (Marchenko-Pastur or Ledoit-Wolf shrinkage). Recent 2024-25 arxiv work (`arxiv:2410.20597` financial analyst networks; `arxiv:2601.05428` bounded multi-factor tilts) shows that **explicit correlation cleaning** at the signal-combination step matters more than the choice of model — naively averaging correlated signals doubles your effective bet size on whatever factor they share.

Dedup is best done in two passes: (1) **content dedup** at the news/idea level via SimHash or embedding-cosine (>0.85 = dup, take highest-authority source), which the reader's stack already does at the Awarebot tier; (2) **exposure dedup** at the trade-construction level via beta to sector ETF / SPY. If two ideas resolve to the same sector ETF exposure within 0.7 beta, they are one position. The CMU/MIT trading-systems consensus: never compose more than ~25% of gross exposure from signals that share the same source-of-edge label (e.g. "options flow" or "news sentiment").

**Do this:** maintain a `signal_id -> {source_cluster, sector_etf, factor_loadings}` index, compute pairwise correlation of *open positions* (not signals), and gate new ideas against a max-pairwise-correlation cap (0.6 is the conservative bar). **Not that:** don't trust per-source dedup alone — two different sources reporting the same thing is still one bet.

### 2. Position sizing math (Kelly vs ATR vs vol-targeting)

The 2024 consensus, reinforced by the Polymarket / prediction-market literature and the BSIC Kelly-extension paper, is that **full Kelly is theoretically optimal but operationally insane** — the drawdown profile crushes psychology and triggers risk-off behaviour at the wrong moment. Professionals use **half-Kelly or quarter-Kelly** (multiplier 0.25-0.5 of f*), with a hard cap that total active exposure stays under 25-30% of bankroll regardless of what individual Kelly says. The formula `f* = (bp - q) / b` only holds for independent binary bets; for continuous-payoff equity trades, use the variance-form `f* = μ / σ²` and then halve.

**Volatility targeting (Carver's approach)** is the dominant institutional pattern: set a portfolio volatility target (e.g. 20% annualized for an aggressive retail book; 10-15% for CTAs), back out per-position notional from target/√N × σ_position, and let the *number* of uncorrelated bets scale your effective Kelly fraction. Carver shows that 4-6 uncorrelated trend strategies effectively triple your Sharpe vs one. **ATR-based stops** (1-2x ATR for trend, 2-3x ATR for swing, 0.5-1x for mean reversion) are an *execution* tool, not a sizing tool — size from vol-target, place stops from ATR.

For correlated bets, the standard collapse: if ρ ≈ 1, treat as one position sized at the *combined* Kelly. If ρ ≈ 0.5, the effective Kelly for the pair is roughly Σf_i / (1 + (N-1)ρ). The reader's mix (trend + swing + stat-arb + mean reversion + carry) is naturally low-correlation, which is the right architecture — the bandit can lean into whichever sleeve is winning without breaking the diversification math.

**Do this:** vol-target at the portfolio level (target = 15-20% annualized), Kelly-scale at the strategy level (half-Kelly with floor at 0.25%, ceiling at 2% per trade), ATR for stop placement only. **Not that:** never let Kelly recommend >5% on a single name without an explicit override; never apply Kelly off a fitted in-sample win rate (use the credible lower bound from your Beta-Bernoulli posterior, which the reader already has).

### 3. Risk governance (heat caps, correlation, beta-adjusted, drawdown, circuit breakers)

The hedge-fund / prop-desk standard, codified in checklists like Resonanz Capital's manager-assessment template, is a **layered limit cake**: per-trade (R or % NAV), per-strategy/sleeve (gross + net + max DD), per-sector (gross long + short, e.g. ±25% of NAV per GICS sector), portfolio gross (typically 150-300% for L/S, ≤150% for trend), portfolio net (e.g. -20% to +60%), beta-adjusted net (which converts notional into market-equivalent exposure using rolling-60d beta to SPY). Prop desks add a **VaR/CVaR cap** (1-day 99% VaR ≤ 3-5% NAV) as a final guardrail.

Drawdown throttles are the most under-built control in retail-grade bots. The institutional pattern: tiered step-down (5% DD → cut sizing 25%; 10% → cut 50%; 15% → halt new opens until 5d recovery). Academic work (`arxiv:1710.01503` drawdown-modulated feedback control) proves this can mathematically guarantee a max-DD bound — the reader's risk governor already implements the spirit but should formalize the levels. Circuit breakers are different from throttles — they are **hard force-stops** (3% daily loss, 2 consecutive losing days, drift-detector firing, broker connection drop), not "reduce sizing."

**Do this:** ship a 3-tier drawdown throttle (5/10/15%), a per-sector cap (±20% NAV using sector ETF beta-mapping), beta-adjusted net exposure cap (±50% beta-weighted to SPY), and a daily-loss circuit breaker that fires `state = drawdown_halt` and requires manual resume. **Not that:** don't let the bot "trade out of" a drawdown — every academic study shows revenge-trading at small size has worse expectancy than zero trades.

### 4. Strategy learning (bandit families, frequency normalization, retire-vs-explore)

The 2022-2024 bandit-for-trading literature (`researchgate 385097222`, ClausiusPress 2022 Thompson-sampling survey) converges on **Thompson sampling as the winner for trading** because it handles uncertainty natively and degrades gracefully when arms are sparse. UCB tends to over-explore arms with low trade frequency (because the confidence interval stays wide); ε-greedy is brittle to ε scheduling; contextual bandits (LinUCB, neural bandits) shine when you have rich context features but require enough trades per context to fit — usually not the case for individual retail strategies.

**Frequency normalization** is the trap the reader needs to design around: a PEAD strategy might fire 2x per quarter (high quality, low N); a mean-reversion bot might fire 10x per day. Naively Thompson-sampling over per-strategy posteriors lets the high-frequency arm dominate. The two fixes: (1) **reward normalization** — record `reward = R_multiple × time_in_market_adjustment` so a quarterly PEAD winner of +2R gets more credit than a 30-minute mean-rev winner of +0.5R; (2) **per-strategy capital budget** — pre-allocate sleeve weights (e.g. 30% trend / 25% swing / 15% stat-arb / 10% MR / 10% PEAD / 10% factor) and let Thompson decide *which trade within sleeve* to take, not *which sleeve to be in*.

Retirement is a separate question. The Sharpe-ratio convergence math says you need ~100 trades to distinguish a Sharpe-1 strategy from zero with 95% confidence. Below 30 trades, all bandit estimates are noise. The professional pattern: **never retire below N=50; never promote above paper without N=100**. Drift-detector firing should pause-and-research, not retire.

**Do this:** keep Thompson over closed-form sleeves with per-sleeve capital caps; gate retirement on (N≥50 AND credible-LCB hit-rate <30%) for 30 days; let drift trigger pause+SHAP analysis, not retirement. **Not that:** don't use a single global bandit over all individual setups — the variance is too high and you'll thrash.

### 5. Drift / regime detection (Page-Hinkley vs ADWIN vs CUSUM vs KSWIN)

The 2025 capstone comparison (AUA `Capstone-2.pdf`) and the 2022 autoregressive-drift paper (`arxiv:2203.04769`) confirm what the reader's stack already chose: **Page-Hinkley is the right default for financial streams** — it has the lowest false-positive rate on stationary noise, the lowest RAM/compute cost (~0.00005 RAM-hours vs KSWIN's 0.01262), and detects mean-shift drift cleanly. ADWIN is better for *distribution* drift (variance change, fat tails), not just mean drift. KSWIN (Kolmogorov-Smirnov windowed) is best when you suspect *shape* changes (regime flips that don't change the mean but change the tail). CUSUM is the parent of PH and works fine but PH's lambda parameter is easier to tune.

The senior insight: **no single detector catches all regime shifts**. The best-engineered systems run an *ensemble* — PH on the win/loss stream (the reader already has this), ADWIN on the P&L distribution, plus a separate macro regime classifier (Hidden Markov on SPY returns + VIX + breadth). Recent 2024 HMM-trading work (`questdb.com/glossary/market-regime-detection`) shows that 2-state HMMs (high-vol / low-vol) reliably improve Sharpe by 0.3-0.5 across multiple strategies by simply turning trend off in high-vol regimes.

The reader's existing cycle_phase classifier (Wave 14I) is already in this spirit — combining it with PH at the strategy level gives **two-level drift detection**: macro regime change pauses all strategies in that bucket, micro PH pauses individual losing strategies. The composition rule: if cycle_phase = recession AND strategy_pH = DRIFT_DOWN, force-halt; if only one fires, throttle.

**Do this:** keep PH at strategy level, add ADWIN on portfolio P&L distribution (catches variance regime change PH misses), wire cycle_phase as the macro layer. **Not that:** don't tune drift thresholds against historical paper data — they'll overfit. Set lambda from theory (Kullback-Leibler-divergence equivalent thresholds) and accept some false positives.

### 6. Graduation criteria (paper to live, CTA emerging-manager bars)

CME / NilssonHedge / institutional allocator standards for funding an emerging CTA give a converging picture. The bars (across CME's "Evaluating CTAs" course, Van Tharp SQN literature, and StrategyQuant practitioner thresholds):

- **Sample size**: minimum N=100 closed trades; 250+ preferred. Sub-N=30 is statistical noise.
- **Hit rate**: ≥45% for trend (with 1.5+ payoff), ≥55% for mean-reversion (with 1.0 payoff). Bare minimum.
- **Profit factor (PF)**: ≥1.5 for systematic CTA funding; ≥2.0 to attract allocator interest. PF<1.3 means edge is fragile.
- **System Quality Number (SQN)**: ≥1.7 acceptable, ≥2.5 good, ≥3.0 excellent. Below 1.7 = noise.
- **Expectancy in R**: ≥0.20R per trade is the institutional minimum; ≥0.50R is strong.
- **Max DD**: ≤20% of NAV for the strategy in isolation; ≤15% combined portfolio.
- **Recovery time**: max-DD recovered within 2-3x the time-to-DD (otherwise the curve has a *secular* problem).
- **Time in market**: minimum 6 months paper for a daily-frequency strategy; 12 months for swing; 18-24 months for trend with quarterly fires.
- **Lower-bound Bayesian hit rate (credible LCB)** ≥ 40% — the reader's existing gate, which is the most modern and least-gamed metric.

Industry seed allocators (Old Hill, NewAlpha, Stable Asset) typically demand a **Calmar ≥ 0.7**, **Sortino ≥ 1.5**, and **no negative quarter exceeding -8%** during the live track. The graduation gate's multi-criteria weighting (the reader's existing 8-criteria design) maps directly to this — keep the weights, raise the bars to industry levels.

**Do this:** keep the 8-criteria gate; tighten min_sqn from 1.7 → 2.0, add Calmar ≥ 0.7 and "no -8% quarter" as binary gates. **Not that:** don't graduate on a single great quarter — require the criteria to hold across 2 consecutive rolling 60-day windows.

### 7. Execution modeling (slippage, partial fill, microstructure realism)

Almgren-Chriss (2000, refined through 2024 arxiv work `arxiv:2603.29086`) is the field standard for **modeling realistic execution cost in simulation**. The square-root impact law `Δp ≈ σ × √(Q/V) × η` (where Q is order size, V is daily volume, η is a stock-specific constant ~0.1-0.5) gives temporary impact; the permanent impact is ~1/3 of temporary for liquid US equities. For a retail-scale ($36K) book, **temporary impact is negligible** (Q/V << 1bp), but **spread + commission + slippage** dominate.

The realistic friction model for paper-to-live transfer:
- **Stocks**: 3-5 bps slippage + half-spread + $0.005/share commission. Add 2 bps for after-hours.
- **ETFs**: 1-3 bps slippage + half-spread. SPY/QQQ are tighter (<1 bp).
- **Options**: 5-10 bps of underlying for ATM, 50-100 bps for OTM. Partial fills are common — model 60-80% fill rate at midpoint, 100% at NBBO.
- **Crypto**: 10-20 bps on major pairs (BTC/USD), 30-50 bps on alts. Funding rate matters for carry.
- **Futures**: 1-2 ticks slippage on /ES, /NQ in market hours; 3-5 ticks overnight.

The reader's friction profile (3 bps stocks / 50 bps options + 5% partial / 10 bps crypto / 15 bps futures) is in the right ballpark; the K6b calibration loop that EMA-blends observed slippage is exactly correct — that's how paper-vs-live divergence closes over time. The one missing piece: **time-of-day modeling**. Spreads at 9:30 ET are 2-3x wider than 10:30 ET; if the bot fires market orders in the first 5 min, paper underestimates cost by ~10 bps. Add an `intraday_friction_multiplier` (1.5x for 9:30-9:35, 1.3x for 9:35-9:45, 1.0x for 10:00-15:30, 1.5x for 15:55-16:00).

**Do this:** add intraday friction multiplier; keep K6b EMA calibration. **Not that:** don't ignore borrow cost for short positions (the reader's stack is long-only paper, but if ever adding shorts: 50-300 bps annualized borrow on hard-to-borrow names).

### 8. Observability & explainability (audit, attribution, regulator-ready logs)

The CFTC's Regulation AT (algorithmic trading) and FINRA Notice 15-09 set the institutional bar: **immutable audit trail of every decision** including pre-trade risk check, model output, parameter set, source code version, and post-trade reconciliation. While the reader is paper-only (so not subject), building to these standards now makes future live transition trivial.

The minimum required log per trade decision (CFTC AT Person standard):
1. `trade_idea_id` + timestamp + source signals (with hashes for immutability)
2. Model/strategy ID + version + parameter snapshot
3. Pre-trade risk check (governor decision + reasoning)
4. Sizing math (Kelly inputs + multiplier + final position)
5. Friction model applied (slippage + partial fill seed)
6. Execution outcome (fill price, partial, time-to-fill)
7. Post-trade attribution (alpha / beta / factor / noise decomposition)
8. Outcome reconciliation (closed P&L vs predicted)

The reader's per-trade reasoning chain capture is already this shape. The missing piece is **attribution decomposition**: every closed trade should be broken into (a) market beta — what would SPY have done?, (b) factor exposure — what would the Fama-French 5-factor predict?, (c) sector/industry effect, (d) idiosyncratic alpha — the residual. The Hudson & Thames / Fidelity Fusion-Alpha pattern is to log this as a vector per trade so monthly reviews can decompose performance into "is our edge real, or are we just long the market in disguise?"

**Do this:** add a `post_trade_attribution` module that fits market+factor exposures over rolling 60 trades per strategy and decomposes returns. Surface in the dashboard. **Not that:** don't conflate Sharpe ratio with alpha — a 1.0 Sharpe purely from market beta is worth 0; a 0.5 Sharpe of pure alpha is worth 10x more after fees.

### 9. LLM-in-the-loop trading (where they help, where they hurt)

The TradingAgents framework (`arxiv:2412.20138`, Dec 2024) and FinAI Contest 2025 evidence converge: LLMs add value in **narrative synthesis, news triage, multi-source contradiction surfacing, and council-style debate over qualitative regime questions**. LLMs HURT in **direct sizing, stop placement, execution timing, and any numerical computation that has a deterministic answer**. The "Liar Circuits" paper (`arxiv:2511.21756`) and FAITH (`arxiv:2508.05201`) show LLMs hallucinate arithmetic with high frequency — never let an LLM compute position size, even with a calculator tool, without a deterministic re-check.

The pattern that works in production (per TradingAgents v3 and the reader's existing Council architecture): **LLMs propose, math disposes**. LLM generates the *idea* (which ticker, why, expected catalyst), a deterministic risk governor sizes it, a deterministic stop-placement rule sets the exit. The reader's Wave 14H-I pipeline (Macro Analyst + Real-Time Pulse + Flow Detective + Technical Tactician → Chair) is exactly the right shape. The one upgrade: add a **post-hoc deterministic critic** that re-reads every LLM-emitted trade idea and checks (a) ticker exists, (b) cited price is within 2% of current, (c) cited catalyst date is in the future, (d) R:R math is correct, (e) sizing is within governor caps. The reader's Wave 14G P17 quality gates already do most of this — extend to auto-trader flow.

Hallucination guards specific to trading (from FAITH benchmark): (1) **fact-anchoring** — every numeric claim must cite a signal_id from the prep pack; if the LLM emits a number with no signal_id, reject. (2) **range-bounds** — every price must be within the symbol's 52-week range ± 2%. (3) **catalyst-temporal** — every "by date X" claim must be parsed and verified as future. (4) **arbitration via majority** — if 3 of 4 council members agree on direction, take it; if split, pass.

**Do this:** add a deterministic critic between LLM idea-gen and risk governor (the K-extension would be K8 "LLM Critic Gate"); never let an LLM see the Kelly formula or stop math. **Not that:** don't let an LLM update strategy parameters or graduation criteria — that's the kind of drift you can't audit.

### 10. Self-correction loops (closing outcome → bandit → next sizing)

The reader's Phase 5 (K4) self-research loop is the right architecture, and the open-source examples (FreqEnt, Hummingbot v3 RL extensions, QuantConnect Lean Live Algorithm Framework) confirm the pattern. The canonical closed loop:

1. **Trade closes** → `outcome_attributor` writes R-multiple, time-in-market, stop-type
2. **Bandit updates** → Beta-Bernoulli posterior shifts; Thompson sample on next tick uses new posterior
3. **SHAP attribution** → after every 10 closes per strategy, recompute per-feature lift; SHAP lifts ≥0.10 push synthetic outcomes into source-authority learner (the reader already has this — it's the most modern bit)
4. **Drift check** → PH on rolling win/loss; DRIFT_DOWN → auto-pause + topic generation
5. **Loss-cluster research** → ≥3 losses in (sector, source, stop_type, rotation) bucket → human-readable research topic emitted → manual or LLM-assisted root-cause
6. **Friction calibration** → every 10 closes, EMA-blend observed slippage into profile
7. **Brief feedback** → next morning's brief sees `brief_context_packet` (strategy expectancy, drift state, open research topics) so idea generation biases toward winning sleeves

The reader has all 7 already. The one gap: **explicit prior re-anchoring on regime change**. When cycle_phase transitions (e.g. mid_cycle → late_cycle), the Beta-Bernoulli priors should *reset* (or at least decay toward uninformative) for strategies that are regime-sensitive — otherwise stale "this was a winning strategy in mid_cycle" priors poison late_cycle Thompson samples. The literature calls this "stationarity break re-priors." Implementation: on cycle_phase transition, multiply (α, β) by 0.3 for affected strategies (keeps direction but widens uncertainty).

**Do this:** wire cycle_phase transitions into bandit prior decay. **Not that:** don't auto-resume from drawdown_halt — let it require a human or a 24h cool-down with explicit conditions met (drift back to STABLE, 5 paper-validation trades).

### 11. Common failure modes (the 10 things that kill paper-to-live transfer)

Aggregated across the algo-trading-failure literature (arongroups, FasterCapital, Gainium, nurp.com, Cracking Markets US-momentum deep dive):

1. **Look-ahead bias** — using close to size a trade you "took" at noon. Fix: hard timestamp gate on signal_time < decision_time.
2. **Survivorship bias** — testing on today's S&P 500 (excludes the ones that delisted). Fix: point-in-time universe.
3. **Overfit recipes** — 50-parameter strategies that fit noise. Fix: max 5 params, walk-forward, Lopez-de-Prado purged-CV.
4. **Leverage creep** — Kelly + vol-target + drawdown recovery all push leverage up when you should be cutting. Fix: hard leverage cap independent of any sizing math.
5. **Correlation blindness** — 5 "uncorrelated" longs all loaded on momentum factor. Fix: rolling factor decomposition (covered in #8 above).
6. **Regime hangover** — strategy was great in QE; doesn't work post-QE. Fix: cycle_phase-aware bandit priors (covered in #10).
7. **Fee/slippage underestimation** — single biggest paper-vs-live gap. Fix: friction profile + intraday multiplier + EMA calibration.
8. **Paper-vs-live psychology** — sized 2x in paper, can't pull trigger in live. Fix: gradual capital ramp + small live size first.
9. **Single-source fragility** — bot dies if Awarebot down. Fix: every loop wraps external deps in CircuitBreaker (the reader's Wave 14K Phase 8 does this — confirm coverage).
10. **Silent data-quality bugs** — stale price, bad ticker, split-adjustment miss. Fix: pre-trade sanity check (52-week range, daily move <30%, volume >0).

**Do this:** add a `pre_trade_sanity` gate before governor (the 4 quick checks above). **Not that:** don't silently skip on bad data — log loudly and bump an "data quality" memory unit at importance 80.

### 12. Schedule architecture (cron pattern wisdom)

The institutional cron pattern (synthesized from QuantConnect Lean live-algo defaults, FreqTrade scheduler, Hummingbot v3 patterns, and the reader's existing 43 ncl-* tasks):

- **Tick loop (60s market / 300s off)** — entry decisions, position monitoring. The reader's `ncl-auto-trader-loop` is right.
- **Price feed (10-30s market / 300s off)** — mark-to-market. Reader's `ncl-auto-trader-prices` at 30s is right.
- **Scanner sweeps (5-15 min)** — GOAT/BRAVO/RRG. Don't over-poll; signals decay slower than 1 min.
- **Attribution updates (per-close + nightly)** — per-trade attribution on close; portfolio-level Fama-French at 3am ET.
- **Drift checks (every 50 trades or daily, whichever first)** — PH update on stream; ADWIN nightly on distribution.
- **EOD summary (16:30 ET)** — daily P&L, attribution rollup, strategy-level scorecard, post to memory at importance 85.
- **Weekly research (Sun 18:00 ET)** — loss-cluster analysis, research topic generation, graduation gate review.
- **Monthly portfolio review (1st of month, 06:00 ET)** — Calmar/Sortino/Sharpe per strategy, retire-or-explore decisions, prior decay.
- **Quarterly regime re-baseline** — HMM re-fit, factor exposures re-estimate, friction profile reset-to-defaults if drifted >50%.

The single most-violated rule: **don't run heavy compute on the tick loop**. The tick should do ≤200ms of work; everything else is deferred to async tasks. The reader's circuit breakers around tracker/governor/paper-engine + asyncio.to_thread for JSON writes is correct.

**Do this:** add a monthly portfolio-review cron that emits a strategy scorecard + retire/explore recommendations. **Not that:** don't fire scanners every tick — 5 min is plenty and reduces both cost and noise.

### 13. Mandate framing (prop desk / managed account hedge-fund-style)

The institutional mandate template (from Resonanz Capital checklist, CME CTA evaluation, NYC Comptroller emerging-manager strategy):

- **Strategy description**: 1-paragraph plain-English (what edge, what universe, what holding period)
- **Risk budget**: target annualized vol (15%), max DD (15%), Sharpe target (1.0+), Calmar (0.7+)
- **Sleeve allocation**: % capital per sub-strategy with hard floors/ceilings
- **Universe**: explicit ticker list or filter rule (e.g. "US large-cap ex-financials, ADV>$50M")
- **Stop-out triggers**: NAV drops 15% from peak → 50% deallocation; 20% → 100% halt + 30d cooldown
- **Success metrics**: net-of-fees Sharpe >1, max DD <15%, alpha (factor-adjusted) >5%/yr
- **Governance**: who approves param changes, who has kill-switch, audit cadence

The reader's auto-trader is implicitly mandated by code — the upgrade is to write an **explicit mandate doc** that lives in `~/dev/NCL/docs/AUTO_TRADER_MANDATE.md` and gets ingested as procedural memory (importance 95). This makes every decision auditable against "did we follow the mandate?" and gives the bandit a clear objective function.

**Do this:** write the mandate doc; cite it in every trade reasoning chain. **Not that:** don't let mandate drift silently — version it in git and re-ingest on change.

### 14. Paper-to-live transition

The Alpaca / TradersPost / VTMarkets practitioner consensus on transition:

1. **Capital ramp**: start at 10% of intended live size for 30 days, 25% for next 30, 50% for next 30, 100% after 90 days of clean live data. Never go from $0 → $36K live overnight.
2. **Identical execution path**: paper and live use the same code, only the broker adapter swaps. The reader's PaperTradingEngine + IBKR/Moomoo/SnapTrade adapter pattern is correct.
3. **Latency benchmarking**: log signal_time → order_time → fill_time at every stage. Live will be 50-500ms slower than paper; if your edge depends on <100ms, you don't have an edge.
4. **Wash sale awareness**: don't sell at a loss and rebuy within 30d in a taxable account — IRS disallows the loss. Tag every close with `wash_sale_window_end` and gate re-entry.
5. **Real fill quality**: track per-order `slippage_realized` vs `slippage_predicted`. The K6b EMA calibration that the reader already has is the right vehicle for closing this gap.
6. **Connection robustness**: live broker connections drop; the bot must handle reconnect-with-state-recovery. The reader's circuit breaker + state.json persistence is correct.
7. **Tax-lot accounting**: live trading requires FIFO vs LIFO tracking. Paper engine should be upgraded to track lots even in sim so the transition is seamless.
8. **Manual kill switch**: a single REST endpoint `POST /auto-trader/emergency-stop` that closes all positions and disables the bot until manual resume. The reader has resume/pause; add emergency-stop with position-flatten.

**Do this:** before any live consideration, implement the 10-25-50-100% capital ramp logic and the emergency-stop endpoint. **Not that:** don't transition to live based on paper Sharpe alone — require the graduation gate AND 90 days of live shadow-mode (live execution, $1 size, paper accounting) first.

---

## (b) Top 10 Highest-Leverage Upgrades (ranked)

Ranked by `(expected impact on edge or risk) × (low implementation cost) × (closes a known gap in current Wave-14K stack)`:

1. **Pre-trade sanity gate** — 4-check filter (ticker exists, price within 52w range, daily move <30%, volume >0) before risk governor. Cheap to ship, catches the entire "stale data / hallucinated ticker" failure class. ~50 LOC.

2. **Intraday friction multiplier** — extend FrictionProfile with time-of-day multiplier (1.5x first/last 5 min, 1.0x mid-day). Closes the biggest realism gap in paper-to-live transfer. ~30 LOC.

3. **Cycle-phase-aware bandit prior decay** — on cycle_phase transition, multiply (α,β) × 0.3 for regime-sensitive strategies. Stops stale "winning in mid_cycle" priors from poisoning late_cycle Thompson samples. ~80 LOC.

4. **Post-trade factor attribution** — fit Fama-French 5-factor + sector exposures over rolling 60 trades per strategy; decompose returns into alpha/beta/factor/noise; surface in dashboard. The single biggest "are we actually generating alpha?" question this answers. ~250 LOC.

5. **3-tier drawdown throttle (formalize)** — 5% → cut sizing 25%, 10% → cut 50%, 15% → halt. The reader's risk governor has the hooks; this just formalizes the levels. ~40 LOC.

6. **Beta-adjusted exposure cap** — rolling-60d beta to SPY per position, portfolio beta-adjusted net capped at ±50% NAV. Catches "5 longs all loaded on momentum" failure mode. ~150 LOC.

7. **ADWIN on portfolio P&L distribution** — complement to per-strategy Page-Hinkley; catches variance regime change PH misses. River library is one import. ~100 LOC.

8. **Per-sector cap (±20% NAV)** — map every position to sector ETF, sum exposure, gate new opens. Cheap correlation-blindness fix. ~100 LOC.

9. **Explicit AUTO_TRADER_MANDATE.md doc + procedural memory ingest** — codifies risk budget, sleeve allocation, success metrics. Makes every decision auditable and gives bandit a clear objective. ~1 doc + 10 LOC ingest.

10. **Monthly portfolio review cron** — 1st-of-month task that emits strategy scorecard (Calmar/Sortino/Sharpe/alpha-decomposition per sleeve), retire/explore recommendations, prior re-anchoring. Closes the "who's looking at this weekly?" gap. ~300 LOC scheduler task + LLM brief.

Just below the line: emergency-stop endpoint (high importance but lower complexity); deterministic LLM critic gate for trade ideas (covered by Wave 14G P17); tax-lot accounting upgrade (needed only for live transition); time-of-day intraday vol model (covered by friction multiplier).

---

## (c) Further reading (8-15 sources)

1. **Marcos López de Prado** — *Advances in Financial Machine Learning* (Wiley 2018) + ssrn meta-labeling / purged-CV papers. The bible on validation, triple-barrier, and avoiding backtest overfitting. https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086

2. **Robert Carver** — *Systematic Trading* (Harriman 2015) + blog `qoppac.blogspot.com`. Definitive on vol-targeting, diversification multiplier, forecast-combination. https://qoppac.blogspot.com/2018/07/vol-targeting-and-trend-following.html

3. **Ernie Chan** — *Quantitative Trading* + *Algorithmic Trading* + *Machine Trading*. Practical implementation patterns for mean reversion, momentum, factor strategies. https://www.epchan.com/books/

4. **Almgren & Chriss** — "Optimal Execution of Portfolio Transactions" (2000) + Gatheral's "No-Dynamic-Arbitrage and Market Impact" notes. Foundation for execution cost modeling. https://mfe.baruch.cuny.edu/wp-content/uploads/2012/09/Chicago2016OptimalExecution.pdf

5. **TradingAgents framework** — Xiao et al., *TradingAgents: Multi-Agents LLM Financial Trading Framework* (arxiv 2412.20138, Dec 2024). Best current paper on LLM-agent trading architecture. https://arxiv.org/abs/2412.20138

6. **FAITH benchmark** — *FAITH: Framework for Assessing Intrinsic Tabular Hallucinations in Finance* (arxiv 2508.05201, 2025). Critical for LLM-in-loop hallucination guards. https://arxiv.org/pdf/2508.05201

7. **AUA Capstone — Concept Drift Detection in Finance** (Pluzyan 2025). PH vs ADWIN vs KSWIN head-to-head on financial streams. https://cse.aua.am/wp-content/uploads/2025/06/Capstone-2.pdf

8. **Hudson & Thames blog** — meta-labeling, triple-barrier, signal efficacy. Best practitioner content on Lopez-de-Prado-style ML. https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/

9. **QuantStart** — Michael Halls-Moore's articles on HMM regime detection, backtesting traps, QSTrader patterns. https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/

10. **CME Group — Evaluating CTAs: Quantitative and Qualitative Factors**. Industry standard for strategy graduation bars. https://www.cmegroup.com/education/courses/managed-futures/evaluating-ctas-quantitative-and-qualitative-factors

11. **QuantConnect Lean** — open-source institutional-grade algo framework. The reference for live-algo architecture. https://github.com/QuantConnect/Lean

12. **FreqTrade docs** — practical autonomous-bot patterns, hyperopt, strategy lifecycle. https://www.freqtrade.io/

13. **NYC Comptroller — Diverse and Emerging Manager Strategy**. Allocator perspective on graduation criteria. https://comptroller.nyc.gov/services/financial-matters/pension/responsible-investing/diverse-and-emerging-manager-strategy/

14. **Resonanz Capital — Hedge Fund Manager Risk Management Checklist**. Institutional risk-governance template. https://resonanzcapital.com/insights/checklist-for-assessing-hedge-fund-managers-risk-management-approach

15. **CFTC Regulation AT proposal + Akin Gump analysis**. Forward-looking regulatory bar for algo trading audit trail. https://www.akingump.com/en/insights/alerts/cftc-proposes-significant-new-regulations-for-algorithmic

Bonus — **arxiv:1710.01503** "Drawdown-Modulated Feedback Control" — mathematical proof that tiered drawdown throttles can guarantee max-DD bounds. https://arxiv.org/pdf/1710.01503

---

*End of research notes. Next stage: convert top-10 upgrades into discrete Wave 14L tickets.*
