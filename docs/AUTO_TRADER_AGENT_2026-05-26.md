# Auto-Trader Agent — Wave 14K Architecture

**Date**: 2026-05-26
**Wave**: 14K prep
**Scope**: An autonomous **paper-trading** agent that consumes NCL's morning brief + GOAT/BRAVO scanner + council output, opens paper trades through the existing `PaperTradingEngine`, tracks outcomes, and feeds the results back into the J1d expectancy tracker so each strategy's actual hit rate calibrates the upstream recommendations over time.

**Explicitly NOT live trading**. Paper only. The "no live executor" rule from Wave 14J is fully intact — `order_preview.py` is the human-in-the-loop substitute for real money. This wave is shadow-trading: validation, learning, and proving theses without capital at risk.

---

## TL;DR

NCL already has every primitive the auto-trader needs:

| Need | Source |
|---|---|
| Trade ideas with entry/stop/target/R per share | Wave 14J J1c (brief_pipeline.py executor schema) |
| Stable IDs across emit → close | Wave 14J J1d (trade_idea_tracker.py) |
| Heat caps + drawdown throttle in one gate | Wave 14J J1a+J1b (risk_governor.py) |
| Per-strategy expectancy stats | Wave 14J J1d (trade_idea_tracker.expectancy_by_strategy) |
| Paper-trade open/close/mark-to-market | PaperTradingEngine + /paper REST routes |
| Rotation pacing + breadth veto + counter-trend stance | Wave 14J J3a/b/c (rotation_execution.py) |
| Wash-sale + earnings-proximity sizer | Wave 14J J4a/c/d (tax_compliance.py) |
| Drawdown band as global throttle | Wave 14J J0c (drawdown_bucket.py) |
| Memory bridge for outcome attribution | Wave 12 + 13 (memory_bridge, async_writer) |
| Circuit-breaker pattern for adapter failures | Wave 14J J8c (hygiene.CircuitBreaker) |

The missing piece is the **decision loop** that connects all of these. That loop is what Wave 14K builds.

---

## 1. Current State — What NCL Already Has

### 1.1 Trade-idea feedstock

After Wave 14J, every trade idea emitted by the morning brief pipeline (and by extension GOAT/BRAVO scanners and council output) carries:

```json
{
  "trade_idea_id": "16-char-hex",
  "issued_at_iso": "2026-05-26T...",
  "type": "stock | options | futures",
  "ticker": "NVDA",
  "direction": "long | short",
  "thesis": "1-sentence thesis",
  "entry_price": 185.0,
  "stop_price": 178.0,
  "stop_type": "price | atr | volatility | time | thesis_break",
  "stop_basis": "below 50d SMA",
  "target_price": 215.0,
  "target_basis": "prior swing high",
  "R_per_share": 7.0,
  "planned_qty": 100,
  "sources": ["signal_id_1", "signal_id_2"],
  "rotation_quadrant": "Leading | Improving | Weakening | Lagging",
  "rotation_stance": "with_trend | counter_trend | neutral",
  "rotation_pacing": {"stage_1": {...}, "stage_2": {...}, "stage_3": {...}},
  "breadth_veto": {"vetoed": false, "reason": "..."},
  "governor_decision": {"approved": true, "decision": "approve", "effective_R_dollars": 700}
}
```

`runtime/portfolio/trade_idea_tracker.py` registers each idea with `outcome="emitted"` and exposes:
- `record_emission()` — adds idea
- `update_outcome(trade_idea_id, outcome, exit_price, notes)` — closes loop
- `expectancy_by_strategy()` — per-strategy rollup (hit_rate, avg_win_R, profit_factor, SQN, expectancy_R)

### 1.2 PaperTradingEngine surface (`runtime/portfolio/paper_trading.py`, 750 LOC)

| Method | Purpose |
|---|---|
| `create_trade(data)` | Validates fields, auto-sizes if qty=0, R:R ≥ 1.0, JSONL persist |
| `update_prices({sym: px})` | Per-tick mark-to-market; auto-triggers stop/target/trailing/time exits |
| `close_trade(id, exit_price, reason, grade, notes)` | Applies slippage, computes final R, immutable record |
| `update_trade(id, updates)` | Edit metadata (notes/grade/tags); cannot edit closed trades |
| `get_stats()` | win_rate, expectancy_R, profit_factor, SQN, equity_curve, **graduation readiness** |
| `get_open_symbols()` | Symbol list for the live-quote feeder |

Defaults: $10K starting balance, 2% max risk per trade, slippage 0.05% stock / 0.50% option / 0.10% crypto, max hold 30 days. All configurable.

Built-in **graduation criteria** (already present, line 703-722): N ≥ 30 closed trades, win_rate ≥ 45%, profit_factor ≥ 1.5, rules_followed ≥ 90%.

REST surface under `/paper/*`:
- `POST /paper/trade` — open
- `GET /paper/trade/{id}` — full detail
- `POST /paper/trade/{id}/close` — close with exit
- `GET /paper/trades` — list with filters
- `POST /paper/prices` — batch price update
- `GET /paper/stats` — full rollup

### 1.3 Risk gates

Every proposed trade can be checked via `check_proposed_trade()` in `risk_governor.py`:

```python
{
  "approved": bool,
  "decision": "approve | throttle | reject",
  "reasons": ["..."],
  "effective_R_dollars": float,    # after drawdown multiplier
  "sizing_multiplier": float,      # 1.00 / 0.75 / 0.50 / 0.00
  "band": "green | caution | warning | halt",
  "heat": {...}
}
```

This is the single gate the auto-trader must pass through before every paper-trade open. No bypass paths.

### 1.4 Memory + observability

- `memory_bridge.py` already emits `portfolio:*` units for live-portfolio events
- `async_writer.py` provides fire-and-forget memory persistence (won't block the trading loop)
- `hygiene.CircuitBreaker` is a generalized 3-strike/10-min skip pattern any subsystem can wrap

### 1.5 What's missing — the loop

There is **no autonomous loop** today that:
1. Polls `trade_idea_tracker` for ideas in `outcome=="emitted"` state
2. Filters them through an entry-criteria policy
3. Submits each to `risk_governor.check_proposed_trade()`
4. Opens the approved ones via `PaperTradingEngine.create_trade()`
5. Periodically fetches live quotes for `get_open_symbols()` and calls `update_prices()`
6. On trigger events, links the closing trade back to its `trade_idea_id` via `update_outcome()`
7. Emits memory units + computes rolling expectancy drift
8. Surfaces "due for graduation review" when a strategy crosses the threshold

Wave 14K is that loop.

---

## 2. Industry + Academic Best Practice (P27-A research)

Twelve+ sources synthesized below — full citations in the appendix.

### 2.1 Architecture pattern — multi-agent with simulated trading as primary learning substrate

**TradingAgents** (arXiv 2412.20138, 59.9k stars) and **QuantAgents** (arXiv 2510.04643) both validate the same shape:
- Multi-role specialists (fundamental / sentiment / technical / risk) feed
- Bull/Bear debate which feeds
- A trader that produces an idea which is checked by
- A risk-management agent before execution

NCL has this already — the Wave 14H Morning Brief Pro council (Macro / Pulse / Flow / Technical / Chair). What's missing is the next step: **simulated trading as the primary feedback signal back into all of them**. QuantAgents specifically uses paper-trade outcomes both for "real market" feedback AND for "predictive accuracy" feedback that updates each agent's prior.

### 2.2 Trading-R1 thesis structure (arXiv 2509.11420)

Trading-R1 was trained specifically to produce **facts-grounded, volatility-adjusted, evidence-based investment theses** with structured reasoning chains. Direct lift for NCL: when the auto-trader records a trade open, capture the full chain (which signals + which prompts + which model + which version + which confidence). When the trade closes, **the entire reasoning chain becomes the unit of attribution**, not just the strategy tag.

### 2.3 Sequential Bayesian update on strategy success rate

The Beta-Bernoulli conjugate pair: posterior = Beta(α + wins, β + losses). NCL already uses this for source authority. **Promote it one level up to strategy success rate**, refreshing on every paper-trade close. Each strategy gets a posterior distribution over its true hit rate, and the auto-trader can compute `P(strategy_hit_rate > 0.5 | observed_history)` directly.

Source: https://chenghanyang728.medium.com/bayesian-belief-updating-made-easy-the-beta-bernoulli-conjugate-pair-2c9800922f04

### 2.4 Thompson sampling for arm selection

When N strategies are competing for capital under uncertain win rates, Thompson sampling beats arg-max. **Sample** a draw from each strategy's posterior; pick the arm with the highest draw. This keeps under-performing strategies in rotation until the data definitively rules them out (poly-log regret bounds).

Application: when a brief emits 6 trade ideas and the heat budget only allows 3, sample which ideas to take rather than always picking the ones from the historically-best strategy. This is exploration discipline.

Source: https://gdmarmerola.github.io//ts-for-contextual-bandits/

### 2.5 SHAP attribution on closed trades

After ≥30 closed trades, run SHAP over the (signal_id, source, sector, rotation_aligned, breadth, VIX, RVOL) feature set against win/loss labels. **Which inputs actually predicted outcomes** is the most actionable feedback the system can produce — it tells the brief pipeline which signals to weight more in future prompts. Caveat: average across multiple SHAP runs because single-run attributions are noisy.

Source: https://arxiv.org/pdf/1802.03888

### 2.6 Concept drift detection — Autoregressive Drift Detection Method (ADDM)

ADDM was designed specifically for identifying market regime changes and triggering strategy review. Apply to the auto-trader: when ADDM signals drift on the strategy's hit-rate time series, **pause paper-trading that strategy and emit a high-importance memory unit** ("GOAT scanner hit-rate drift detected on 2026-XX-XX; consider regime-aware re-spec").

Source: https://blog.quantinsti.com/autoregressive-drift-detection-method/

### 2.7 Champion/challenger A/B testing

100% of brief signals go to the **champion** strategy mix; **challengers** see the same signals in parallel without affecting the operator-facing brief. Statistical tests on hit_rate / SQN / expectancy_R determine when a challenger gets promoted.

Application for NCL: the champion is the current strategy mix (GOAT/BRAVO/options/polymarket); a challenger could be e.g. "GOAT but only rotation-aligned with breadth>50%". Both consume the same morning brief; both paper-trade in parallel; the metrics tell the operator which to promote in 30 days.

Source: https://www.datarobot.com/blog/introducing-mlops-champion-challenger-models/

### 2.8 Idempotent event-sourced trade ledger

Every trade lifecycle event (emit → take → fill → MAE tick → MFE tick → exit) appended to an append-only log with state-machine invariants (PENDING → OPEN → CLOSED, forward-only). Crash recovery = replay log from last snapshot. NCL's `trade_idea_tracker` and `paper_trading` already do this; the auto-trader loop must preserve the same guarantee — **never modify a row in place, only append**.

Source: https://quant.engineering/exchange-order-book-distributed-logs.html

### 2.9 Paper-to-live graduation criteria

Industry consensus on minimum sample size: 30 trades for CLT, 100+ for reliable inference, 200+ for "confident", 500+ across regime states for high confidence. Plus quality: 80 clean independent > 300 correlated. Plus regime coverage: don't graduate during a regime shift (cycle_phase confidence < 0.35 = "mixed" → hold).

Multi-criteria gate for NCL:
```
GRADUATE if:
  N_closed                     ≥ 30
  AND SQN                      ≥ 2.0
  AND profit_factor            ≥ 1.5
  AND friction-adjusted Sharpe > 0
  AND regimes_covered          ≥ 2  (cycle_phase ≥ 2 distinct phases)
  AND current_regime_confidence > 0.35
  AND walk_forward_OOS_degradation < 30%
```

Sources: https://medium.com/@trading.dude/how-many-trades-are-enough-..., https://journalplus.co/metrics/system-quality-number/

### 2.10 Verbalized confidence — size by it, don't gate on it

Research (arXiv 2412.14737) is unambiguous: LLMs' verbalized confidence is calibrated enough to **weight by** but mostly fails to convert to a good abstention policy. NCL implication: use the brief's confidence_pct field as a sizing multiplier on `effective_R_dollars` for paper trades, but don't use it as a gate.

Source: https://arxiv.org/abs/2412.14737

### 2.11 Inject realistic frictions into paper sims

Paper trading systematically over-performs live by 15-20% because of instant fills, no slippage, no partial fills, no emotion. Calibration data: average slippage 5-15 bps on liquid US equities, 30-80 bps in vol spikes. NCL's `PaperTradingEngine` already records slippage; Wave 14K must add a **friction profile** per strategy (conservative/normal/aggressive) so the simulated P&L is conservative-vs-live, not optimistic-vs-live.

Sources: https://markrbest.github.io/paper-vs-live/, https://blog.traderspost.io/article/the-reliability-of-paper-trading-insights-and-best-practices

### 2.12 Observability — every trade carries its reasoning chain

The audit trail requirement: each paper trade open captures (User, Agent, Tool) triple-identity, prompt hash, model + version, confidence emitted, signal IDs cited, full critic decision. LangFuse (self-hostable, free at unlimited scale) is the natural upgrade for the trace side; NCL's `cost_tracker.py` already owns the spend side.

Source: https://langfuse.com/docs/observability/features/token-and-cost-tracking

### 2.13 Synthesis principles

1. **Shadow trader, not live trader** — every reference frames the autonomous agent as parallel-to, not in-place-of, the operator. Wave 14K respects this absolutely.
2. **Reuse existing NCL primitives** — Wave 14K is composition, not greenfield. Beta-Bernoulli, planner→executor→critic, cycle_phase, R-multiples, cost gates all exist.
3. **Multi-criteria graduation gate** — never a single number.
4. **Confidence weights, doesn't gate** — verbalized confidence research is unambiguous.
5. **Idempotent + event-sourced from day one** — never modify in place; append-only ledger with state-machine invariants.

---

## 3. Architecture — Auto-Trader Agent (Wave 14K)

### 3.1 Module map (proposed)

```
runtime/portfolio/auto_trader/
├── __init__.py
├── policy.py               # Entry-criteria policy: which ideas pass auto-bar
├── loop.py                 # Main scheduler loop: poll → policy → governor → open
├── price_feed.py           # Live-quote feeder for open paper symbols
├── outcome_attributor.py   # On close: link to trade_idea_id, update tracker, emit memory
├── strategy_bandit.py      # Thompson sampling over strategies (Beta-Bernoulli posterior)
├── friction_profile.py     # Per-strategy slippage/spread/partial-fill calibration
├── graduation_gate.py      # Multi-criteria check for "ready for live promotion"
├── drift_detector.py       # ADDM on per-strategy hit rate; pause on drift
└── observability.py        # Trade reasoning chain capture (prompt + model + sources)
```

REST surface (new):
- `GET  /portfolio/auto-trader/status` — current state, open paper trades count, daily activity
- `GET  /portfolio/auto-trader/policy` — current entry-criteria
- `PATCH /portfolio/auto-trader/policy` — operator-tune thresholds
- `POST /portfolio/auto-trader/pause` — manual pause (also auto-pauses on drawdown halt)
- `POST /portfolio/auto-trader/resume`
- `GET  /portfolio/auto-trader/expectancy` — Bayesian posteriors per strategy
- `GET  /portfolio/auto-trader/graduation/{strategy}` — graduation readiness report
- `GET  /portfolio/auto-trader/drift` — current drift signals per strategy

Scheduler tasks (new):
- `ncl-auto-trader-loop` — 1m cadence in market hours, 5m off-hours
- `ncl-auto-trader-prices` — 30s cadence (mark-to-market open paper trades)
- `ncl-auto-trader-graduation` — daily at 04:00 ET (post-overnight rollup)

### 3.2 Entry-criteria policy (the auto-bar)

Default policy (operator-tunable via `PATCH /policy`):

```python
def auto_open_eligible(idea: dict, governor_decision: dict) -> tuple[bool, str]:
    # Hard gates
    if not governor_decision["approved"]: return False, "governor rejected"
    if governor_decision["band"] == "halt": return False, "drawdown halt"
    if idea.get("breadth_veto", {}).get("vetoed"): return False, "breadth veto"

    # Quality gates
    if idea.get("R_per_share", 0) <= 0: return False, "no R defined"
    if not idea.get("stop_price"): return False, "no stop set"
    if not idea.get("target_price"): return False, "no target set"

    # R:R floor
    entry, stop, target = idea["entry_price"], idea["stop_price"], idea["target_price"]
    rr = abs(target - entry) / abs(entry - stop) if entry != stop else 0
    if rr < 1.5: return False, f"R:R {rr:.2f} below 1.5 floor"

    # Source citation requirement
    if not idea.get("sources"): return False, "no source citations"

    # Stop-type whitelist
    if idea.get("stop_type") not in {"price", "atr", "volatility", "time", "thesis_break"}:
        return False, f"invalid stop_type {idea.get('stop_type')!r}"

    # Strategy-specific extras
    strat = (idea.get("strategy_tag") or idea.get("type") or "").lower()
    if strat in ("goat", "momentum"):
        # GOAT setups: require with-trend rotation alignment
        if idea.get("rotation_stance") == "counter_trend":
            return False, "GOAT counter-trend — operator review only"

    return True, "passed auto-bar"
```

### 3.3 Decision loop (~1m cadence)

```
LOOP:
  1. Read drawdown_bucket.get_state() → if band == "halt", sleep + continue
  2. Read trade_idea_tracker.list_by_strategy(None) filtered by outcome=="emitted"
  3. For each emitted idea NEWER than last_seen_iso:
       a. Compute auto_open_eligible(idea, idea.governor_decision)
       b. If NOT eligible, log + continue (idea stays in emitted; operator can act)
       c. Strategy bandit: Thompson-sample arm; if not picked, skip
       d. Compute effective_R = governor.effective_R_dollars × verbalized_confidence
       e. Compute qty = max(1, effective_R / R_per_share)
       f. PaperTradingEngine.create_trade(idea + qty + slippage_profile)
       g. trade_idea_tracker.update_outcome(idea.trade_idea_id, "taken")
       h. observability.record_reasoning_chain(idea, governor_decision, model_meta)
       i. Emit memory unit: portfolio:auto_trade_opened (importance 75)
  4. Update last_seen_iso
  5. Sleep until next tick
```

### 3.4 Price feed (~30s cadence)

```
LOOP:
  1. symbols = PaperTradingEngine.get_open_symbols()
  2. quotes = quote_source.default_quote_chain().get_many(symbols)
  3. triggered_events = PaperTradingEngine.update_prices(quotes)
  4. For each event where event.type in {stop_hit, target_hit, trailing_stop, time_exit}:
       a. PaperTradingEngine handles close internally → close_trade(reason)
       b. outcome_attributor.on_paper_close(closed_trade):
            - Look up trade_idea_id from closed_trade.scanner_data (set at open)
            - trade_idea_tracker.update_outcome(trade_idea_id, outcome=event.type, exit_price)
            - strategy_bandit.record_result(strategy, win_loss)
            - drift_detector.update(strategy, hit_rate_window)
            - Emit memory unit: portfolio:paper_trade_closed (importance 80)
  5. Sleep
```

### 3.5 Outcome attribution mapping

| PaperTrade exit_reason | trade_idea_tracker outcome |
|---|---|
| `closed_target` | `target_hit` |
| `closed_stop` | `stopped_out` |
| `closed_trail` | `manually_closed` (interpreted as profit trail) |
| `closed_time` | `expired` |
| `closed_manual` | `manually_closed` |

The R_multiple is computed by both engines; the values must reconcile within 1¢ — surface mismatch as `[OUTCOME-DRIFT]` warnings.

### 3.6 Self-learning feedback (Bayesian + Thompson)

```python
class StrategyBandit:
    def __init__(self):
        # Beta(1,1) = uniform prior per strategy
        self.posteriors = defaultdict(lambda: {"alpha": 1, "beta": 1})

    def record_result(self, strategy: str, win: bool):
        if win:
            self.posteriors[strategy]["alpha"] += 1
        else:
            self.posteriors[strategy]["beta"] += 1

    def sample_arm(self, candidates: list[str]) -> str:
        # Thompson sampling: draw from each posterior, pick max
        draws = {
            s: beta_distribution.rvs(
                self.posteriors[s]["alpha"],
                self.posteriors[s]["beta"]
            )
            for s in candidates
        }
        return max(draws, key=draws.get)

    def credible_interval(self, strategy: str, ci: float = 0.95) -> tuple[float, float]:
        a, b = self.posteriors[strategy]["alpha"], self.posteriors[strategy]["beta"]
        return beta_distribution.interval(ci, a, b)
```

When `credible_interval(strategy, 0.95)` excludes 0.40 from below, the strategy has demonstrated > 40% true hit rate with high confidence → graduation gate can fire.

### 3.7 Self-healing patterns

- **Every external dependency wrapped in `hygiene.CircuitBreaker`** (J8c): quote source, trade_idea_tracker reads, governor checks. 3-strike → 10m quarantine.
- **Graceful degradation**: stale quotes → quote_ok=false → suppress price feed update (don't close on stale data).
- **Drawdown halt = auto-pause** auto-trader, retain open positions, no new opens.
- **Adapter failure**: log, emit alert via central `enqueue_alert`, continue (paper-only — no real-money risk).
- **Crash recovery**: ledger is JSONL append-only; on Brain restart, replay from snapshot.

### 3.8 Self-researching feedback into upstream

The most powerful learning step: closed paper trades drive what NCL researches next.

```
On every 10th closed trade (per strategy):
  1. SHAP attribution over (signal_source, sector, rotation_aligned, RVOL,
     breadth, VIX, time_of_day) vs win/loss
  2. If top-attributed feature is "rotation_aligned == True", boost rotation
     signal weight in the next morning brief prompt
  3. If most losses came from "sources contains specific scanner X",
     downgrade scanner X authority tier in SourceAuthorityLearner
  4. Emit a memory unit at importance 90: "STRATEGY-LEARN: GOAT win rate
     conditional on rotation_aligned: 73% (n=15) vs 41% (n=27) un-aligned"
```

This is what makes the system self-improving rather than just self-running.

### 3.9 Friction profile

```python
FRICTION_PROFILES = {
    "conservative": {
        "stock_slippage_bps": 15,        # 0.15% (high end of normal)
        "option_slippage_bps": 80,       # 0.80%
        "partial_fill_threshold_pct": 5, # 5% of avg minute volume → partial fill
        "gap_through_penalty": 1.0,      # full gap-through penalty
    },
    "normal": {
        "stock_slippage_bps": 8,         # 0.08%
        "option_slippage_bps": 50,
        "partial_fill_threshold_pct": 10,
        "gap_through_penalty": 0.5,
    },
    "aggressive": {
        "stock_slippage_bps": 3,         # close to PaperTradingEngine default
        "option_slippage_bps": 25,
        "partial_fill_threshold_pct": 20,
        "gap_through_penalty": 0.0,
    },
}
```

Default = `conservative` for first 100 trades, then operator can flip to `normal` once the auto-trader has a track record.

---

## 4. Wave 14K Roadmap

Eight phases, ~25 tasks. Aligned with Wave 14J's phase shape so it's predictable.

### Phase 1 — Foundation (~2d)
- **K0a**: `runtime/portfolio/auto_trader/` package skeleton + observability primitives
- **K0b**: Entry-criteria policy module + REST GET/PATCH /auto-trader/policy
- **K0c**: Drawdown auto-pause wiring (read J0c, pause loop on halt band)

### Phase 2 — Decision loop (~3d)
- **K1a**: Main `loop.py` — poll trade_idea_tracker, apply policy, gate via governor
- **K1b**: Link trade_idea_id → paper_trade.scanner_data at open time
- **K1c**: Memory unit emission on auto-open
- **K1d**: New scheduler task `ncl-auto-trader-loop` + factory registration

### Phase 3 — Price feed + outcome attribution (~2d)
- **K2a**: `price_feed.py` — quote_source.default_quote_chain wiring
- **K2b**: `outcome_attributor.py` — paper close → trade_idea_tracker.update_outcome
- **K2c**: Memory unit emission on paper close
- **K2d**: `ncl-auto-trader-prices` scheduler task at 30s cadence

### Phase 4 — Self-learning (~3d)
- **K3a**: `strategy_bandit.py` — Beta-Bernoulli posteriors + Thompson sampling
- **K3b**: REST `/auto-trader/expectancy` exposes posteriors + credible intervals
- **K3c**: Brief pipeline reads bandit weights to bias trade-idea allocation
- **K3d**: SHAP attribution on closed trades (every 10th close per strategy)

### Phase 5 — Self-researching (~3d)
- **K4a**: SHAP-driven authority adjustments (SourceAuthorityLearner)
- **K4b**: Strategy-learn memory units (importance 90) with regime context
- **K4c**: Auto-research topic generation from losing-trade clusters
- **K4d**: Brief pipeline consumes "strategy-learn" memory units for next-day prompts

### Phase 6 — Drift detection + graduation gate (~2d)
- **K5a**: ADDM drift detection on per-strategy hit-rate windows
- **K5b**: Auto-pause strategy on drift signal; emit high-importance alert
- **K5c**: Multi-criteria graduation gate (SQN/N/PF/Sharpe/regime coverage)
- **K5d**: REST `/auto-trader/graduation/{strategy}` readiness report

### Phase 7 — Realistic frictions + iOS surface (~2d)
- **K6a**: Friction profile injection on paper-trade open (slippage + partial-fill)
- **K6b**: Per-strategy friction calibration from observed live-vs-paper drift
- **K6c**: iOS PaperTradingView (Mac + iOS) — auto-trader live status + recent fills

### Phase 8 — Self-healing + tests + docs (~2d)
- **K7a**: Circuit breakers around every external dep (quote, governor, tracker)
- **K7b**: Crash recovery test (replay ledger from snapshot)
- **K7c**: `tests/test_auto_trader.py` — full lifecycle + drift + bandit + grad gate
- **K7d**: Update CLAUDE.md with Wave 14K summary

Total estimate: ~17-20 dev-days. Same arc-shape as Wave 14G (desktop) and Wave 14J (portfolio risk).

---

## 5. Explicit non-goals

- **No live trading.** Live order placement stays out of NCL forever. `order_preview.py` is the human-in-the-loop substitute. Audit-doc literature unanimous.
- **No new broker adapters.** The 6 existing + manual + mock cover every case. Auto-trader runs against `PaperTradingEngine`, period.
- **No real-money capital allocation logic.** Heat caps in `risk_governor.py` are denominated in dollars but the auto-trader operates in *paper* dollars. Same math, no live consequence.
- **No replacement for operator judgment.** The auto-trader proves theses; the operator graduates strategies, sizes positions in real money, and makes the final call.

---

## 6. Sources referenced

**Multi-agent paper-trading frameworks**
- TradingAgents — https://arxiv.org/abs/2412.20138 / https://github.com/TauricResearch/TradingAgents
- Trading-R1 — https://arxiv.org/abs/2509.11420
- QuantAgents — https://arxiv.org/abs/2510.04643
- FinRobot — https://arxiv.org/abs/2405.14767 / https://github.com/AI4Finance-Foundation/FinRobot
- BloombergGPT — https://arxiv.org/abs/2303.17564

**Self-learning + Bayesian**
- Beta-Bernoulli — https://chenghanyang728.medium.com/bayesian-belief-updating-made-easy-the-beta-bernoulli-conjugate-pair-2c9800922f04
- Thompson sampling — https://gdmarmerola.github.io//ts-for-contextual-bandits/
- SHAP — https://arxiv.org/pdf/1802.03888
- ADDM concept drift — https://blog.quantinsti.com/autoregressive-drift-detection-method/
- Champion/challenger — https://www.datarobot.com/blog/introducing-mlops-champion-challenger-models/

**Self-healing**
- Idempotent state machines — https://blog.devgenius.io/idempotency-in-system-design-full-example-80e9027e7bea
- Circuit breakers — https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker
- Event-sourced trade ledger — https://quant.engineering/exchange-order-book-distributed-logs.html
- Graceful degradation — https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_mitigate_interaction_failure_graceful_degradation.html

**Graduation criteria**
- Van Tharp SQN — https://journalplus.co/metrics/system-quality-number/
- Sample size — https://medium.com/@trading.dude/how-many-trades-are-enough-a-guide-to-statistical-significance-in-backtesting-093c2eac6f05
- Walk-forward — https://blog.quantinsti.com/walk-forward-optimization-introduction/

**Observability**
- LLM audit trails — https://medium.com/@kuldeep.paul08/the-ai-audit-trail-how-to-ensure-compliance-and-transparency-with-llm-observability-74fd5f1968ef
- LangFuse — https://langfuse.com/docs/observability/features/token-and-cost-tracking
- Verbalized confidence — https://arxiv.org/abs/2412.14737

**Prompt patterns**
- Anthropic Advisor Strategy — https://www.mindstudio.ai/blog/anthropic-advisor-strategy-cut-ai-agent-costs
- Anti-hallucination — https://medium.com/@taotang757/my-ai-kept-hallucinating-citations-heres-the-code-that-fixed-it-353d0dbc0d78

**Paper-trading realism**
- Paper-vs-live overperformance — https://markrbest.github.io/paper-vs-live/
- Slippage calibration — https://www.elitetrader.com/et/threads/ib-slippage-paper-vs-live.328024/
- Position sizing (Kelly) — https://medium.com/@jpolec_72972/position-sizing-strategies-for-algo-traders-a-comprehensive-guide-c9a8fc2443c8
