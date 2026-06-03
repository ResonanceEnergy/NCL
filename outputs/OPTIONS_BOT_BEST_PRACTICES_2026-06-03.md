# OPTIONS BOT BEST PRACTICES — TRADERAGENT Audit Reference

**Date**: 2026-06-03
**Scope**: Personal/paper-only systematic options bot. Mac Studio scale. No live-broker integration.
**Subject of audit**: NCL TRADERAGENT (`runtime/portfolio/auto_trader/`, ~2,500 LOC, 60s loop, governor + policy + paper engine + bandit + drift + SHAP + friction profiles)

---

## 1. ENTRY CRITERIA — IVR-Gated Strategy Selection

**Principle.** The single most-validated entry filter for options is **IV Rank (IVR)**. IVR ranks the current 30-day implied vol against the trailing 52-week high/low (0–100). Tastytrade's published research on 200,000+ trades anchors the entire framework around this metric. Strategy selection is a *function* of IVR, not a fixed preference.

**Why it matters.** Options have a structural edge in one direction depending on whether IV is rich or cheap. Selling premium when IV is cheap is negative expectancy in disguise; buying premium when IV is rich is paying the house. A bot that emits the same strategy regardless of IV is decoupled from the only durable edge available to a retail options trader.

**Concrete thresholds.**

| IVR | Regime | Preferred strategies | Why |
|-----|--------|---------------------|-----|
| > 50 | RICH | Short premium: short strangle/straddle, iron condor/butterfly, credit vertical, cash-secured short put | IV mean-reverts down → vega works for you |
| 30–50 | NEUTRAL | Size down 50%, or wait. Defined-risk only. | No structural edge in either direction |
| < 30 | CHEAP | Long premium: long call/put, debit vertical, calendar, diagonal | Vol expansion + directional convexity |

Additional entry gates that should be hard-required:

- **DTE window**: Open positions at **30–60 DTE** (45 DTE is the tastytrade canonical mid-point). Avoid 0–7 DTE (gamma risk overwhelms theta) and >75 DTE (capital efficiency collapses) unless the strategy explicitly trades gamma (0DTE SPX) or calendar structure.
- **Delta target**: Short premium = ~30-delta short strike (16–30 range for wings). Long premium = 40–60 delta. The bot must explicitly tag `target_delta` per idea or refuse to open.
- **Defined risk vs naked**: Naked short puts/strangles are only acceptable on cash-secured underlyings (NAV-funded). Anything else must be **defined-risk** (spread, condor, butterfly). For a personal paper bot, default **defined-risk only** until graduated.
- **Liquidity**: Reject any underlying with option open interest < 500 at the target strike or bid/ask spread > 5% of mid. Wide spreads eat real edge.
- **Earnings filter**: Block new opens within **±5 trading days of earnings** unless the strategy explicitly trades the IV crush (short strangle with earnings playbook).

**Sources.**
- [Volatility Metrics on tastytrade (IVR/IV%/IVx/HV)](https://support.tastytrade.com/support/s/solutions/articles/43000539059)
- [IV Rank on thinkorswim: How to See It (2026 Guide)](https://www.financialtechwiz.com/post/implied-volatility-rank-thinkorswim/)
- [How to use Implied Volatility (IV) Rank in Options Trading](https://www.warriortrading.com/implied-volatility-iv-rank/)

---

## 2. POSITION SIZING — R-Multiple Breaks on Options

**Principle.** Stock-style R-multiple sizing (`risk = |entry - stop| × qty`) breaks down for options because (a) options have non-linear payoffs (gamma), (b) the "stop" is rarely the strike, (c) max-loss is bounded by premium for long, or by spread-width for defined-risk. The right primitive for options is **defined max-loss as a percentage of NAV**, optionally Kelly-scaled.

**Why it matters.** TRADERAGENT's "R:R below 1.0 floor" rejection is the symptom — the engine is trying to apply equity-stop arithmetic to a contract whose payoff curve is convex. Premium decay, not price-stop, is the dominant risk driver.

**Concrete thresholds.**

- **Defined-risk max loss per trade**: **0.5–2.0% of NAV** (paper or live). For a $25K paper account that's $125–$500 max risk per trade.
- **Premium cap for long debit**: Premium paid ≤ **1% of NAV** per position. A $25K account caps long-call cost at $250.
- **Spread width-to-NAV**: For credit verticals, spread width × contracts × 100 ≤ **2% of NAV**.
- **Fractional Kelly**: After ≥100 closes per strategy, switch to **half-Kelly** sizing: `size = 0.5 × (W/L_avg − (1−W)) × NAV`, capped at 2% NAV. Never trust full Kelly — options fat tails punish it.
- **Vega cap per position**: Position vega ≤ **0.5% of NAV per 1 vol point**. Stops a single short-strangle from eating the book on a vol spike.
- **Portfolio vega cap**: Net vega ≤ **±2% of NAV per vol point**, hard-stamped before every open.
- **Beta-weighted delta cap**: Net portfolio beta-weighted delta ≤ **20% of NAV** in either direction. Forces directional balance.

**Sources.**
- [Options Position Sizing: Kelly Criterion Explained (Longbridge)](https://longbridge.com/en/academy/options/blog/options-position-sizing-kelly-criterion-explained-100160)
- [Sizing the Risk: Kelly, VIX, and Hybrid Approaches in Put-Writing (arXiv 2508.16598)](https://arxiv.org/html/2508.16598v1)
- [Position Sizing Using the Kelly Criterion (Options Hawk)](https://optionshawk.com/position-sizing-using-the-kelly-criterion/)

---

## 3. EXIT MANAGEMENT — Profit Targets, 21 DTE, Theta vs Gamma

**Principle.** Tastytrade's published 200,000-trade dataset shows that the **50% profit target + 21 DTE hard close** is the single highest-impact mechanical exit rule in retail options. Closing at 21 DTE improved risk-adjusted returns 15–20% vs. holding to expiry. The reason is structural: gamma risk dominates theta inside 21 DTE, so the seller's edge inverts.

**Why it matters.** TRADERAGENT's `stop_type=thesis_break` is the engine rejecting an equity-style stop on options — correctly — but with nothing to replace it. Options require **time-based + percentage-of-max-profit** exits, not price stops.

**Concrete thresholds by strategy.**

| Strategy | Profit target | Stop / Time exit |
|----------|--------------|------------------|
| Short premium (strangle, IC, credit vertical) | **50% of max profit** | Hard close at **21 DTE** regardless of P&L; loss stop = **2× credit received** |
| Long premium (long call/put, debit vertical) | **100% of debit paid** (2× return) | Hard close at **21 DTE** if not at target; loss stop = **50% of debit** (you've lost half the premium) |
| Calendar / diagonal | **25% of debit paid** (calendars have lower theoretical max) | Close at **front-month 21 DTE**; loss stop = **50% of debit** |
| Iron butterfly | **25% of max profit** (more demanding) | Hard close at **21 DTE** |
| 0DTE SPX | **50% of credit** OR **3:00 PM ET** time stop, whichever first | Loss stop = **2× credit** |

Additional rules:

- **Rolling at 21 DTE**: For short premium with unrealized loss, roll forward to next expiry **same strike** (do not chase). Skip the roll if IVR < 30 at roll-time (closing is better than chasing in cheap-vol environments).
- **Defended exits**: When tested (short strike reached), close the untested side for 50% credit. This is the tastytrade "manage the winner" principle.
- **Gamma scalping**: Only for ITM long-premium positions held > 7 DTE. Out of scope for a paper bot at this stage.

**Sources.**
- [Close at Profit Percent Order (tastytrade)](https://support.tastytrade.com/support/s/solutions/articles/43000435423)
- [Why I'll Never Ignore the TastyLive 21 DTE Options Rule Again](https://medium.com/@build.business.side.hustle/why-ill-never-ignore-the-tastylive-21-dte-options-rule-again-cafe84c8f903)
- [21 DTE Rule Explained (Days to Expiry)](https://www.daystoexpiry.com/blog/the-21-dte-rule-explained-when-and-why-to-close-options-positions-early)

---

## 4. REGIME DETECTION — Don't Be a One-Sided Bot

**Principle.** A systematic options bot must select strategy direction (bullish/bearish/neutral) and structure (debit/credit, long/short premium) based on **measurable regime state**, not LLM narrative. Otherwise you get TRADERAGENT's exact failure mode: 100% long ideas regardless of regime.

**Why it matters.** The current bot has zero regime gate above the SHAP per-source weight adjustment that fires every 10 closes. SHAP is a feature-attribution tool, not a regime detector. By the time SHAP shifts weights, you've already taken 10 wrong-side trades. Regime detection must be a **pre-LLM filter** that constrains what the chair is allowed to emit.

**Concrete regime inputs and bias mapping.**

| Regime input | Threshold | Direction bias |
|--------------|-----------|---------------|
| **VIX term structure** (VIX9D / VIX / VIX3M) | Backwardation (VIX9D > VIX > VIX3M) | Defensive: short calls, long puts, debit put spreads. No naked short premium. |
| | Contango (VIX9D < VIX < VIX3M) | Constructive: short put spreads, short strangles OK |
| **VIX absolute** | > 30 | Sell premium aggressively; IVR is almost certainly > 50 |
| | < 13 | Buy premium / calendars; avoid short premium |
| **Yield curve** (10y − 2y) | Inverted > 50bp | Late-cycle → defensive sectors (XLU, XLP, XLV) calls; cyclicals (XLI, XLY) puts |
| | Steepening from inversion | Early-cycle → cyclicals (XLF, XLI) calls |
| **Breadth** (% above 50d SMA) | > 70% | Trending bullish, but extension risk → debit call spreads, not naked calls |
| | < 30% | Capitulation candidate → short put spreads on quality |
| **Sector dispersion** (RRG leading vs lagging spread) | High | Pair trades; long Leading-quadrant calls + Lagging-quadrant puts |
| **Realized vs implied** (HV30 vs IVx30) | IV - HV > 5 vol points | Sell premium |
| | HV - IV > 3 vol points | Buy premium (vol underpriced) |

**Implementation note**: NCL already has a rotation_tracker + cycle_phase + style_ratios module (Wave 14I). Wire those snapshots into a `RegimeFilter` that runs *before* the chair LLM and stamps the allowed strategy set on the idea-emission prompt. The chair should not be free to emit a long call when regime = late-cycle/inverted/contango — the prompt should not contain "long call" as an option.

**Sources.**
- [Detecting VIX Term Structure Regimes (Cristian Velasquez)](https://medium.com/@crisvelasquez/detecting-vix-term-structure-regimes-8f3b1a4ddf15)
- [VIX term structure as a trading signal (Macrosynergy)](https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/)
- [Volatility Regime Shifting (Dozen Diamonds)](https://www.dozendiamonds.com/volatility-regime-shifting/)

---

## 5. RISK-MANAGEMENT KILL SWITCHES

**Principle.** A trading bot needs **multi-layered halts** with independent triggers. TRADERAGENT has drawdown bands and a 3-strike circuit breaker on external deps. That's the start, not the end. Real systematic shops layer 6–10 kill switches that catch different failure modes.

**Why it matters.** A single-layer drawdown halt fires after damage is done. A vega cap, daily P/L cap, and correlation cap fire *before* the position becomes a problem.

**Concrete kill switches.**

| Switch | Trigger | Action |
|--------|---------|--------|
| **Daily P/L floor** | Closed + open P/L < **−3% NAV** intra-day | Pause new opens for the day; existing positions managed normally |
| **Per-strategy heat cap** | Open risk on a single strategy > **8% NAV** | Reject new opens for that strategy |
| **Net portfolio vega cap** | |portfolio vega| > **2% NAV per vol point** | Reject new opens that would add same-sign vega |
| **Net portfolio gamma cap** | Approaching earnings or Fed day: short gamma > **0.05% NAV per $1 underlying move** | Force defined-risk only |
| **Correlation cap** | > **3 open positions on correlated underlyings** (sector or beta corr > 0.7) | Reject new opens in the correlated cluster |
| **Beta-weighted delta cap** | |β-weighted Δ| > **20% NAV** | Reject directional adds; encourage hedges |
| **Weekend-flat rule** | Friday 3:30 PM ET | Force-close all short-gamma positions with < 7 DTE Monday |
| **Earnings blackout** | Underlying earnings within ±5 trading days | Reject new opens (with explicit "earnings_strategy=true" override) |
| **Vol-event halt** | VIX 1-day move > +30% | Pause new opens 24h; existing positions managed normally |
| **Drift halt** (already in TRADERAGENT) | Page-Hinkley drift_down on strategy | Pause that strategy |
| **Consecutive-loss halt** | 5 consecutive losses on a strategy | Pause that strategy 48h |
| **Drawdown bands** (already in TRADERAGENT) | Tiered: 5% / 10% / 15% NAV peak-to-trough | Reduce size / halt strategy / halt bot |

The **per-day P/L cap and consecutive-loss halt** are the highest-ROI additions to TRADERAGENT today — they fire on hours-to-days timescales, not the months it takes drift detection to catch a regime change.

**Sources.**
- [What's New in Option Alpha: February 2026](https://optionalpha.com/blog/whats-new-in-option-alpha-february-2026)
- [Profit and Loss (Option Alpha help)](https://optionalpha.com/help/profit-and-loss)
- [Reading the Greeks: From Delta to Theta for Real P&L Control (Hedgepoint)](https://hedgepointglobal.com/en/blog/options-greeks-from-delta-to-theta)

---

## 6. POST-MORTEM / META-LEARNING — Per-Feature Attribution That Matters

**Principle.** Generic SHAP over outcome features is fine for tabular ML. For options, you need attribution along the **specific axes that determine option P&L**: realized-vs-implied move, days-from-open-to-close, vega P&L vs delta P&L vs theta P&L, fill quality, and IV-rank-at-open.

**Why it matters.** TRADERAGENT's SHAP per-source attribution tells you which signal source winning strategies came from. It doesn't tell you whether your losing strategies lost because IV crushed (vega), price moved (delta), time passed without movement (theta), or you got bad fills (slippage). All four feel the same on a P&L blotter but have completely different fixes.

**Concrete per-trade attribution fields to capture and roll up.**

1. **IV at open vs IV at close** — was the trade an IV trade or a direction trade?
2. **HV during hold vs IV at open** — did the underlying actually move as much as the option market said it would?
3. **Theta captured** — % of theoretical theta you actually received
4. **Delta P&L vs vega P&L vs theta P&L decomposition** — via Black-Scholes attribution
5. **Slippage at open + close** — mid-price vs fill-price in % of credit/debit
6. **Time-in-trade vs planned** — were exits triggered by target, by 21 DTE rule, or by stop?
7. **Strategy bucket × IVR bucket × DTE bucket** — every win-rate stat should be reported sliced this way, not as a single scalar
8. **Tested-vs-realized IV (IV − HV gap)** — the structural edge tastytrade quantifies; if your gap is < 0 across many trades, your edge has inverted

**Roll-up cadence.** Every 25 closes per strategy, emit a memory unit at importance 90 with the per-axis breakdown. That replaces TRADERAGENT's current "every 10 closes per strategy" SHAP feature-lift report with one that lets you actually fix the strategy.

**Sources.**
- [Implied Volatility Explained: The Complete Guide for Options Traders (OptionsJive)](https://optionsjive.com/blog/implied-volatility-explained/)
- [Options Strategy Summary — tasty trade strategies](https://medium.com/@tinman_crypto/options-strategy-summary-9c901bd4873a)
- [The Greeks and Option Risk Management (Brenndoerfer)](https://mbrenndoerfer.com/writing/greeks-option-risk-management-delta-gamma-theta-vega)

---

## 7. PAPER-TO-LIVE GRADUATION GATES

**Principle.** A graduation gate is a *hard-required minimum*, not a soft signal. Every gate must be green simultaneously before any strategy migrates from paper to live. Live trading drawdowns are empirically **1.5×–2× higher** than backtest/paper drawdowns and backtested Sharpe drops by **0.5–1.0 points** in live trading. Graduation gates must build that haircut in.

**Why it matters.** TRADERAGENT already has weighted multi-criteria gates. The risk is treating the weighted score as the verdict instead of treating each criterion as a hard veto.

**Concrete gates (all must pass simultaneously, AND not OR).**

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| **Sample size** | N ≥ **50 closed trades** per strategy (paper bot can use 100 if loop is fast) | Below 50, sample variance dominates; CI on win rate is wider than the mean |
| **Time on paper** | ≥ **90 calendar days** OR ≥ **2 distinct vol regimes** observed | Must include at least one VIX > 25 episode |
| **Hit rate** | ≥ **45%** for premium-selling strategies; ≥ **35%** for long premium | Long premium can be profitable below 50% via convexity |
| **LCB hit rate** (Bayesian lower bound) | ≥ **40%** at 90% credible interval | Hit rate alone overstates; LCB is the honest read |
| **Profit factor** | ≥ **1.5** | Below 1.3 is noise; 1.5–2.0 is workable |
| **Expectancy (R-multiple)** | ≥ **0.10R / trade** | Below this and friction eats the edge |
| **Max drawdown** | ≤ **20% NAV** (paper); expect 30%+ live | Drawdown < 20% in paper = drawdown < ~40% live |
| **Sharpe (annualized)** | ≥ **1.0** in paper; expect 0.0–0.5 live | Sharpe is secondary but a useful gut check |
| **Sortino** | ≥ **1.5** | Penalizes downside specifically |
| **Stable across regimes** | Strategy must be profitable in ≥ **2 of 3** {low-vol, mid-vol, high-vol} buckets | A bot that only works in one regime isn't graduated; it's curve-fit |
| **No recent drift** | Page-Hinkley STABLE for ≥ **14 days** | TRADERAGENT already has this |
| **Slippage realism** | Live-style friction profile applied for last ≥ **20 closes** | If results survive friction, they survive a real broker |

NCL never goes live — TRADERAGENT is paper-only by design. That means graduation is a **decision-support readout for the operator**, not an auto-promotion. Display all 12 gates with red/yellow/green; never compute a single composite score that hides a failed criterion.

**Sources.**
- [Paper Trading: How to Use It Without Fooling Yourself (Obside)](https://obside.com/trading-strategies/paper-trading)
- [Paper Trading Strategy Development Guide (TradersPost)](https://blog.traderspost.io/article/paper-trading-strategy-development-guide)
- [5 Essential Metrics to Evaluate Algo Trading Performance (Nurp)](https://nurp.com/wisdom/5-key-metrics-to-monitor-in-automated-trading-systems/)
- [Profit Factor in Trading (QuantVPS)](https://www.quantvps.com/blog/how-to-calculate-profit-factor)

---

## 8. ANTI-PATTERNS — Failure Modes To Engineer Against

**Principle.** Bots fail in characteristic ways. Catalog them, write detectors, alert on them. TRADERAGENT exhibits at least four of the classic anti-patterns right now.

**Why it matters.** The bot's *current* problems — 423/436 duplicate GRRR ideas, ideas_opened_today=2 vs paper.trades=0, 100% long bias, "R:R 1.00 below 1.0 floor" rejection loops — are not bugs in any single module. They are interaction failures *between* modules whose state has drifted apart.

**Anti-patterns to detect with explicit counters.**

1. **Duplicate-idea emission**. Same `(strategy, ticker, side, day)` re-emitted. **Detector**: bucket emitted ideas by `(strategy, ticker, day)` and reject the 2nd+. **Stamp**: rejection reason `dedup:same_day_resubmit`. TRADERAGENT's current `brief:am` re-emission per loop tick is the textbook example.
2. **State drift between governor / policy / engine**. Each module has its own view of "how many opened today". **Detector**: at the end of each loop, assert `governor.opens_today == policy.opens_today == paper.trades_opened_today`. Log diff; halt if drift > 1 for > 5 minutes.
3. **One-sided emission**. Chair always says BUY/long-call. **Detector**: rolling 50-idea sliding window — if `long_count / total > 0.85` for 50 ideas, halt new emissions and force a regime-check. The fix is *upstream* — constrain the chair prompt by regime, do not just filter the output.
4. **LLM prompt bias**. Researchers have shown LLMs exhibit confirmation bias in investment recommendations and over-recommend popular tickers. **Detector**: track ticker emission distribution; if Herfindahl index > 0.3 over 100 ideas (one ticker dominates), suspect prompt or memory injection bias. Also: include short/put examples in the few-shot prompt — LLMs mirror what they see.
5. **Fake counters**. `ideas_opened_today` increments but `paper.trades_opened_today` does not. **Detector**: every emit-to-open path must end with a single atomic "I opened a trade" call that updates both counters. If the policy gate rejects, neither counter increments. Currently TRADERAGENT is incrementing an "attempted" counter and calling it "opened".
6. **Stale signals**. Same `brief:am` signal_id being scored fresh each tick. **Detector**: signal age must be < 4h for entry; reject older with `dedup:stale_signal`.
7. **Schema-mismatch silent reject**. `stop_type=thesis_break` rejected as invalid → idea swallowed silently. **Detector**: every reject reason category must hit a counter; alert if any single reason > 10% of recent rejects. The fix is to (a) accept `thesis_break` for defined-risk options with a structural exit OR (b) emit a *valid* options stop_type in the chair prompt schema.
8. **Strategy graveyard**. Strategy with N > 200 and edge < 0 still running. **Detector**: any strategy with `expectancy_R < 0 AND N > 100` auto-pauses and emits a research topic. Currently TRADERAGENT's "goat" strategy at N=416, mean win rate 0.48%, avg R = −2.26 should have been auto-paused 300 trades ago.
9. **Survivor-bias backtest**. Strategy bandit Beta-Bernoulli is only updated on *closed* trades — open losers are invisible. **Detector**: include MTM open-position drawdown in the bandit posterior, not just closed-trade outcomes.
10. **No put generation path**. Verify it physically — grep the codebase for emission of `option_right=P` over the last 30 days. If zero, the put-generation code path is dead, not just unused.

**Sources.**
- [Exposing Product Bias in LLM Investment Recommendation (arXiv 2503.08750)](https://arxiv.org/pdf/2503.08750)
- [Your AI, Not Your View: The Bias of LLMs in Investment Analysis (arXiv 2507.20957)](https://arxiv.org/pdf/2507.20957)
- [Biases in Algorithmic Trading (Algotrade Knowledge Hub)](https://hub.algotrade.vn/knowledge-hub/biases-in-algorithmic-trading/)

---

## TOP-10 AUDIT PUNCH-LIST FOR TRADERAGENT

Each item is mapped to an observed problem and to the section above. Format: **ID — Problem → Fix → Reference**.

**P1. Duplicate-idea spam (423/436 = GRRR brief:am).**
Add `(strategy, ticker, day, side)` dedup key + `(signal_id, day)` dedup key. Reject 2nd+ with explicit reason `dedup:same_day_resubmit`. Counter at `/auto-trader/dedup-stats`. Cap per-strategy-per-ticker per-day = 1. **→ §8 anti-pattern #1**

**P2. State drift (`ideas_opened_today=2` but `paper.trades` shows 0 new opens).**
End-of-tick invariant: assert governor.opens_today == policy.opens_today == paper.trades_today. Log diff; halt new opens if drift > 1 for > 5 min. Make emit-to-open atomic — `ideas_opened_today` only increments when paper.create_trade succeeds. **→ §8 anti-pattern #2 + #5**

**P3. 100% LONG bias — no puts, no shorts.**
Add `RegimeFilter` upstream of chair LLM. Stamp `allowed_strategies = [...]` based on VIX term structure + cycle phase + breadth. Constrain chair prompt to only emit from the allowed set. Track rolling 50-idea long/short ratio; alert if > 85% same side. Audit codebase for `option_right=P` emissions in last 30 days — if zero, that path is broken. **→ §4 regime detection + §8 anti-pattern #3, #10**

**P4. "R:R 1.00 below 1.0 floor" repeatedly rejecting options.**
Stop applying equity R:R arithmetic to options. Replace with: defined-risk-max-loss as % of NAV (cap 2%), premium cap (1% NAV for long), vega cap (0.5% NAV per vol point). For credit verticals, R:R = credit / (width − credit) — that arithmetic is structurally < 1 for high-prob strategies and rejecting them is wrong. **→ §2 position sizing**

**P5. `stop_type=thesis_break` rejected by engine as invalid.**
Either accept `thesis_break` for defined-risk options (no price stop, exit on structural signal + 21 DTE + 50% profit target) OR update the chair prompt schema to emit `stop_type ∈ {profit_target_50, time_21dte, stop_loss_2x_credit, defended_winning_side}`. Stop-type validation should be options-aware, not equity-aware. **→ §3 exit management + §8 anti-pattern #7**

**P6. No IVR / IV-rank gate on options entries.**
Hard-require `ivr_at_open` field on every options idea. Reject without it. Add IVR-banded strategy mapper (IVR>50 → short premium; IVR<30 → long premium; 30–50 → neutral/size-down). Refuse to open a short strangle in IVR=15, refuse to open a long straddle in IVR=85. **→ §1 entry criteria**

**P7. "goat" strategy: N=416, win=0.48%, avg R=−2.26 still active.**
Add auto-pause: any strategy with `expectancy_R < 0 AND N > 100` pauses and emits a research-topic memory unit at importance 90. Bandit Thompson-sample should already be giving this near-zero weight — confirm it's actually being applied to the gate. Verify open-position MTM is included in bandit posterior, not just closed outcomes. **→ §8 anti-pattern #8, #9**

**P8. All 6 strategies failing graduation — but no actionable readout of *why*.**
Replace single weighted graduation score with 12-gate red/yellow/green table per strategy. Operator must see which specific gate failed. Add the 3 missing gates: time-on-paper ≥ 90d, LCB hit rate, regime-stability (profitable in ≥ 2 of 3 vol buckets). Display as `/auto-trader/graduation/<strategy>` dashboard. **→ §7 graduation gates**

**P9. SHAP per-source weights every 10 closes is the *only* adaptation — too slow.**
Add per-tick kill switches: daily P/L floor (−3% NAV pauses new opens), consecutive-loss halt (5 losses → 48h pause), portfolio vega cap (2% NAV/vol point), beta-weighted delta cap (20% NAV), correlation cap (3 positions per sector), weekend-flat rule for short gamma, earnings ±5d blackout, VIX +30% 1d halt. These fire in seconds-to-hours, not weeks. **→ §5 kill switches**

**P10. Reasoning chains captured but no options-specific attribution.**
Extend reasoning-chain JSONL with per-trade fields: `iv_at_open`, `iv_at_close`, `hv_during_hold`, `theta_captured_pct`, `delta_pnl`, `vega_pnl`, `theta_pnl`, `slippage_open_pct`, `slippage_close_pct`, `exit_trigger ∈ {profit_target, 21dte, stop, defended, drift_halt}`, `iv_rank_bucket`, `dte_bucket`. Roll-up every 25 closes per strategy as memory unit at importance 90. SHAP-style per-source attribution is fine but secondary to per-axis P&L decomposition. **→ §6 post-mortem**

---

**Sources (consolidated):**
- [Volatility Metrics on tastytrade](https://support.tastytrade.com/support/s/solutions/articles/43000539059)
- [IV Rank on thinkorswim 2026 Guide](https://www.financialtechwiz.com/post/implied-volatility-rank-thinkorswim/)
- [Implied Volatility (IV) Rank Warrior Trading](https://www.warriortrading.com/implied-volatility-iv-rank/)
- [Options Position Sizing: Kelly Criterion Explained (Longbridge)](https://longbridge.com/en/academy/options/blog/options-position-sizing-kelly-criterion-explained-100160)
- [Sizing the Risk: Kelly, VIX, and Hybrid Approaches in Put-Writing (arXiv)](https://arxiv.org/html/2508.16598v1)
- [Position Sizing Using the Kelly Criterion (Options Hawk)](https://optionshawk.com/position-sizing-using-the-kelly-criterion/)
- [Close at Profit Percent Order (tastytrade)](https://support.tastytrade.com/support/s/solutions/articles/43000435423)
- [Why I'll Never Ignore the TastyLive 21 DTE Options Rule Again](https://medium.com/@build.business.side.hustle/why-ill-never-ignore-the-tastylive-21-dte-options-rule-again-cafe84c8f903)
- [21 DTE Rule Explained (Days to Expiry)](https://www.daystoexpiry.com/blog/the-21-dte-rule-explained-when-and-why-to-close-options-positions-early)
- [Detecting VIX Term Structure Regimes](https://medium.com/@crisvelasquez/detecting-vix-term-structure-regimes-8f3b1a4ddf15)
- [VIX term structure as a trading signal (Macrosynergy)](https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/)
- [Volatility Regime Shifting (Dozen Diamonds)](https://www.dozendiamonds.com/volatility-regime-shifting/)
- [What's New in Option Alpha: February 2026](https://optionalpha.com/blog/whats-new-in-option-alpha-february-2026)
- [Profit and Loss (Option Alpha help)](https://optionalpha.com/help/profit-and-loss)
- [Implied Volatility Explained (OptionsJive)](https://optionsjive.com/blog/implied-volatility-explained/)
- [Options Strategy Summary — tasty trade strategies](https://medium.com/@tinman_crypto/options-strategy-summary-9c901bd4873a)
- [The Greeks and Option Risk Management (Brenndoerfer)](https://mbrenndoerfer.com/writing/greeks-option-risk-management-delta-gamma-theta-vega)
- [Paper Trading: How to Use It Without Fooling Yourself (Obside)](https://obside.com/trading-strategies/paper-trading)
- [Paper Trading Strategy Development Guide (TradersPost)](https://blog.traderspost.io/article/paper-trading-strategy-development-guide)
- [5 Essential Metrics to Evaluate Algo Trading Performance](https://nurp.com/wisdom/5-key-metrics-to-monitor-in-automated-trading-systems/)
- [Profit Factor in Trading (QuantVPS)](https://www.quantvps.com/blog/how-to-calculate-profit-factor)
- [Exposing Product Bias in LLM Investment Recommendation (arXiv)](https://arxiv.org/pdf/2503.08750)
- [Your AI, Not Your View: The Bias of LLMs in Investment Analysis (arXiv)](https://arxiv.org/pdf/2507.20957)
- [Biases in Algorithmic Trading (Algotrade Knowledge Hub)](https://hub.algotrade.vn/knowledge-hub/biases-in-algorithmic-trading/)
- McMillan, *Options as a Strategic Investment* (5th ed.) — canonical reference for strategy taxonomy, delta-strike conventions, defensive adjustments.
