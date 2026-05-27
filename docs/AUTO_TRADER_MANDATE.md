# NCL Auto-Trader Mandate v1.0

**Effective**: 2026-05-27
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Pillar**: NCL standalone
**Hard line**: PAPER-TRADING ONLY. NCL never places live orders. Graduation is decision support for the operator, never auto-promotion.

---

## 1. Strategy Description

The auto-trader is a **hedge-fund-manager-in-training experiment** that paper-trades a multi-strategy book sized to match NATRIX's live broker NAV ($36,149 CAD at Wave 14K seed). The agent runs a 5-gate decision chain (sanity → calendar → working-context → governor → friction) on every emitted trade idea, opens paper positions through `PaperTradingEngine`, attributes outcomes back into a Beta-Bernoulli strategy bandit, and surfaces drift / graduation / research signals to the operator.

**Edge sources**: GOAT trend-following (Felix Friends), Johnny Bravo MA-stack swing, pairs stat-arb, mean reversion, post-earnings drift (PEAD), factor tilts, unusual options flow (whale_flow), crypto carry, Polymarket Kelly bets.

**Universe**: US equities + major ETFs (price ≥ $5, ADV ≥ $10M); options on the same; 10 major crypto pairs via yfinance; active Polymarket events. No penny stocks, no foreign exchange ex-USD, no commodities futures (beyond ES/NQ macro context).

**Holding period**: minutes (mean reversion intraday) → days (BRAVO swing 1-10d) → weeks-months (GOAT trend 30-120d) → quarters (LEAP destinations via profit ladder).

---

## 2. Risk Budget

| Metric | Target | Hard Limit |
|---|---|---|
| Annualized portfolio volatility | 15% | 25% |
| Max drawdown | 10% | 15% (halts new opens) |
| Sharpe ratio | ≥1.0 | retire below 0.5 after N≥100 |
| Calmar ratio | ≥0.7 | retire below 0.3 after N≥100 |
| Sortino ratio | ≥1.5 | — |
| Risk per trade | 5% of NAV | hard cap at 6% |
| Max opens per day | 8 | enforced by policy.py |
| Max opens per tick (60s) | 2 | enforced by policy.py |
| Min reward:risk ratio | 1.5 | enforced by policy.py |
| Cooldown after open | 60s | enforced by policy.py |

---

## 3. Sleeve Allocation

Per-strategy heat caps (as % of NAV), enforced by `risk_governor.py`:

| Sleeve | Target % | Cap % | Notes |
|---|---|---|---|
| GOAT (trend) | 30% | 3% heat | 150-SMA gate, with-trend only |
| BRAVO (swing) | 20% | 2% heat | MA-stack 9/20/180, two-tier exit |
| Options | 20% | 4% heat | Spreads only, IV-rank gate |
| Pairs stat-arb | 10% | 3% heat | Z-score reversion, mean = 50d |
| Mean reversion | 5% | 2% heat | RSI<30/>70 entries |
| PEAD | 5% | 2% heat | Earnings ± 3d window |
| Factor tilts | 5% | 2% heat | Value / quality / low-vol |
| Whale flow | 3% | 2% heat | Unusual Whales premium > $1M |
| Crypto carry | 1% | 2% heat | Funding rate arbitrage |
| Polymarket | 1% | 1% heat | Kelly-positive edges only |
| **Total platform heat** | — | **10% of NAV** | enforced by governor |

---

## 4. Stop-Out Triggers

Tiered drawdown response (Wave 14U U5):

| Drawdown band | Action | Sizing multiplier |
|---|---|---|
| 0% to -3% (**green**) | Normal operation | 1.00 |
| -3% to -7% (**caution**) | Throttle new opens 25% | 0.75 |
| -7% to -12% (**warning**) | Throttle new opens 50% | 0.50 |
| -12% to -15% (**halt**) | Halt new opens; manage existing | 0.00 |
| Below -15% | **Manual review required**; 30d cooldown | 0.00 |

**Daily loss circuit breaker**: 3% NAV loss in a single day → auto-pause + ntfy to NATRIX.

**Consecutive-day stop**: 2 consecutive losing days at >2% each → auto-pause + ntfy.

**Drift detector**: Page-Hinkley DRIFT_DOWN on any strategy → auto-pause that strategy + emit research topic.

---

## 5. Success Metrics (graduation criteria)

A strategy is graduated for live-deployment consideration when ALL of the following hold across **2 consecutive rolling 60-day windows**:

| Criterion | Threshold | Weight |
|---|---|---|
| Sample size (closed trades) | N ≥ 100 | 3 |
| Hit rate | ≥ 45% | 1 |
| Profit factor | ≥ 1.5 | 1 |
| System Quality Number (Van Tharp) | ≥ 2.0 | 1 |
| Expectancy in R | ≥ +0.20R | 1 |
| Bayesian credible-LCB hit rate | ≥ 40% | 1 |
| No recent drift (14d) | DRIFT_DOWN not fired | 1 |
| Calmar ratio | ≥ 0.7 | 1 |
| Cycle-phase confidence | ≥ 0.35 | 1 |
| No negative quarter exceeding -8% | true | 1 |

Graduation is **decision support only** — the operator (NATRIX) decides whether to ever promote any strategy to live. The agent does NOT auto-promote.

---

## 6. Governance

| Action | Authority | Mechanism |
|---|---|---|
| Pause/resume agent | NATRIX | REST `POST /portfolio/auto-trader/pause` / `/resume` |
| Modify policy thresholds | NATRIX | REST `POST /portfolio/auto-trader/policy` (versioned, audit-logged) |
| Modify heat caps | NATRIX | env vars `NCL_HEAT_*_PCT` or REST endpoint |
| Approve/veto research topic | NATRIX | REST `POST /portfolio/auto-trader/research/{id}/resolve` |
| **Emergency stop** (flatten all + disable) | NATRIX | REST `POST /portfolio/auto-trader/emergency-stop` (Wave 14U U4) |
| Promote to live | NATRIX (manual only) | NO ENDPOINT — out-of-band decision |

**Audit cadence**:
- Per-trade: reasoning chain → `data/portfolio/auto_trader/reasoning_chains.jsonl`
- Daily: EOD summary at 16:30 ET → memory unit importance 85 + journal entry
- Weekly: Sunday 18:00 ET → loss-cluster analysis + research topic generation
- Monthly: 1st of month 06:00 ET → strategy scorecard (Calmar/Sortino/Sharpe per sleeve) + retire/explore recommendations
- Quarterly: 1st of quarter 06:00 ET → HMM regime re-fit + friction profile reset

**Kill switch**: `POST /portfolio/auto-trader/emergency-stop` flattens all open paper positions, persists `state.active=false` + `state.paused_by="emergency_stop"`, and requires explicit `POST /resume` from NATRIX to re-enable.

---

## 7. Operating principles (do/don't)

**DO:**
- Treat every trade as a probabilistic bet, not a directional conviction.
- Cite source signal_ids on every emission.
- Pre-flight every idea through sanity → calendar → working-context → governor → friction.
- Capture full reasoning chain for every decision (CFTC Reg AT audit standard).
- Throttle on drawdown; halt on circuit breakers; never revenge-trade.
- Let the bandit update on closed outcomes; never override the posterior manually.
- Decay bandit priors on cycle-phase transitions to handle regime change.

**DON'T:**
- Take a trade without a stop price.
- Take a trade with R:R < 1.5 unless explicitly counter-trend (currently disabled).
- Take a trade outside its 52-week price range (sanity gate enforces).
- Bypass the risk governor under any circumstance.
- Auto-promote a strategy to live (operator-only decision).
- Trade in the first 5 min or last 5 min of the session without intraday friction multiplier applied (Wave 14U U3).

---

## 8. Self-* obligations

The agent IS:
- **Self-monitoring** — 4 circuit breakers around external deps (drawdown / governor / tracker / paper engine)
- **Self-learning** — Beta-Bernoulli posterior + Thompson sampling per strategy
- **Self-reflecting** — daily EOD journal, weekly loss-cluster review, monthly scorecard
- **Self-researching** — loss-cluster → research topic → SHAP attribution → authority learner feedback
- **Self-healing** — Page-Hinkley drift detection + auto-pause on DRIFT_DOWN
- **Self-aware** — full reasoning chain persisted per decision, capability registry tracks all 20+ data sources

The agent IS NOT:
- Self-promoting to live trading (operator decision only)
- Self-modifying its mandate (every change is operator-initiated and versioned)
- Self-extending its budget (env-knob overrides require explicit operator action)

---

## 9. Version & audit

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-27 | NATRIX + NCL Wave 14U | Initial mandate codification (was implicit in policy.json) |

Ingested as procedural memory at importance 95 (NATRIX tier) on every Brain boot via the auto-trader subsystem startup hook. Every reasoning chain cites `mandate_version` so audits can trace which mandate revision a decision was made under.

**Mandate cited by**: `loop.py:_emit_open_memory_unit` metadata + `observability.record_reasoning_chain` + every brief `context_packet`.
