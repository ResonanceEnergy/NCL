# Auto-Trader Agent — Research & Roadmap (Wave 14U)

**Date**: 2026-05-27
**Compiled by**: NCL meta-agent (codebase audit + web research synthesis)
**Inputs**: complete read of `runtime/portfolio/auto_trader/*.py` + supporting modules; deep web research on autonomous trading agent best practices 2024-2026; live audit of running agent state.

---

## Part 1 — Current Implementation Map

The auto-trader is **architecturally aligned with 2024-26 best practice**. All major feedback loops are wired. ~5,000 LOC across 25 modules, all under `runtime/portfolio/auto_trader/` plus 4 supporting modules in `runtime/portfolio/`.

### Module map (16 core + 9 supporting)

| Module | Responsibility | Wired? |
|---|---|---|
| `loop.py` | Main 60s/300s decision loop, governor calls, paper opens | ✅ live |
| `state.py` | Operator-controlled active/paused + day counters | ✅ live |
| `policy.py` | Operator-tunable thresholds (min_R_R, max_opens, cooldowns) | ✅ live |
| `observability.py` | Per-decision reasoning chain JSONL + 100-entry cache | ✅ live |
| `price_feed.py` | 30s/300s live quote feeder (runs even when paused) | ✅ live |
| `outcome_attributor.py` | On paper close → tracker → bandit → SHAP → drift | ✅ live |
| `strategy_bandit.py` | Beta-Bernoulli posteriors + Thompson sampling | ✅ live (not yet used for arm selection) |
| `shap_attribution.py` | Per-strategy feature lift; outputs to authority learner | ✅ live (triggers every 10 closes) |
| `drift_detector.py` | Page-Hinkley on per-strategy win/loss stream | ✅ live (auto-pause armed) |
| `graduation_gate.py` | 8-criteria readiness with weighted scoring | ✅ live (0 strategies graduated yet) |
| `friction_profile.py` | Per-strategy slippage + partial-fill profile | ✅ live (calibrates every 10 closes) |
| `strategy_registry.py` | 27 recipes; maps strategy name → bucket | ⚠️ **NOT wired to governor hot path** |
| `capability_registry.py` | Self-aware data-source availability (20+ sources) | ✅ live |
| `quant_scanners.py` | 5 scanners: mean_reversion, pead, factor, pairs, whale_flow | ✅ live |
| `self_research.py` | Loss-cluster topic generation; brief context packet | ✅ live |
| `profit_ladder.py` | Short-dated lottery wins → LEAP destination | ✅ live |
| `calendar_gate.py` | Macro (FOMC/OPEX/quad-witch) + earnings block | ✅ live (non-blocking) |
| `working_context_gate.py` | NATRIX-tier pinned alignment check | ✅ live (non-blocking) |
| `tax_sizing.py` | Wash-sale + earnings proximity multiplier | ✅ live (opt-in block) |
| `council_check.py` | Sonnet+Haiku quorum on high-R opens | ✅ live (non-blocking) |
| `risk_governor.py` (support) | Heat caps + drawdown throttle SPoT | ✅ live |
| `drawdown_bucket.py` (support) | 90-day HWM replay + band classification | ⚠️ **NAV source fragile** |
| `trade_idea_tracker.py` (support) | Issuance→outcome stitching by trade_idea_id | ✅ live |
| `paper_trading.py` (support) | PaperTradingEngine (full lifecycle) | ✅ live |
| `polymarket_agent/*` (support) | Wave 14R polymarket paper bet engine | ✅ live |

### Self-* infrastructure status (audited live)

| Capability | Status |
|---|---|
| Self-monitoring | ✅ 4 circuit breakers all closed |
| Self-learning | ✅ Beta-Bernoulli live (n=2 closes), friction calibrator armed |
| Self-reflecting | ✅ Yesterday's EOD: "evaluated 7, opened 0, rejected 7, closed 3 (2W/1L) for +3.00R" |
| Self-researching | ✅ research_topics endpoint live; capability registry tracks 20+ sources |
| Self-healing | ✅ drift detector idle but armed; auto-pause wired |
| Self-aware | ✅ reasoning_chains.jsonl 88KB and growing |
| Mandate | ✅ revision 2 persisted, "Hedge-fund-manager-in-training, $36K NAV match, 5% risk, 8/day, 2/tick" |

### Today's live activity (audit at 11:30 ET)
- 42 ideas evaluated, **0 opened, 42 rejected**
- 1 open paper position (XLE GOAT @ $59.80, R=-0.90 unrealized)
- 3 closes yesterday (AAPL/AMD/NVDA: 2W/1L, +3R)
- Last loop tick: 1 min ago — loop firing on cadence

### Why 42 rejects today — **two production bugs**

| # | Severity | Bug | Evidence | Root cause | Fix |
|---|---|---|---|---|---|
| 1 | CRITICAL | drawdown bucket reporting dd=-100% | 26/42 rejects: "Drawdown band=halt (dd=-100.0%). All new risk blocked." | NAV source falls through to 0 when broker adapters offline → (0-peak)/peak × 100 = -100% | Add NAV staleness guard in `drawdown_bucket._compute()`; if pm.get_summary() returns 0 or fails, HOLD last band instead of computing |
| 2 | HIGH | strategy_registry not in governor hot path | 16/42 rejects: "Strategy 'unknown' heat would breach cap" | `loop.py:303` passes raw strategy tag to `risk_governor.check_proposed_trade()` without calling `normalize_strategy_via_registry()` first → pairs_stat_arb falls to "unknown" bucket ($1800 cap), trades sized $2058+ always breach | Wire `normalize_strategy_via_registry()` into loop pre-governor step (~5 LOC) |

---

## Part 2 — Best Practices Cross-Walk

What the literature (López de Prado, Carver, Chan, Almgren-Chriss, TradingAgents 2024, FAITH 2025, CME CTA evaluation, CFTC Reg AT) says vs what we have:

### Aligned with best practice ✅
- **Bandit choice**: Thompson sampling is the 2024 consensus winner for trading; we have it.
- **Drift detector**: Page-Hinkley is the right default for financial streams (lowest false-positive, lowest cost); we have it.
- **LLM-in-loop architecture**: "LLM proposes, math disposes" pattern from TradingAgents 2024; our Council → deterministic risk governor follows this.
- **Per-trade reasoning chains**: CFTC Reg AT-grade audit trail; we capture it.
- **Friction calibration**: EMA-blend of observed slippage into profile (K6b); industry standard.
- **Strategy expectancy + graduation gate**: 8-criteria weighted scoring matches CME emerging-CTA bars.
- **Closed-loop self-correction**: 7-step loop (close → bandit → SHAP → drift → cluster → calibrate → brief feedback) matches QuantConnect Lean Live + FreqTrade patterns.

### Below best practice — fixable gaps

| Gap | What literature says | Current state | Effort |
|---|---|---|---|
| **Pre-trade sanity gate** | Mandatory: ticker exists, price within 52w range, daily move <30%, volume >0. Catches "stale data / hallucinated ticker" failure class. | Missing | ~50 LOC |
| **Intraday friction multiplier** | Spreads at 9:30 ET are 2-3x wider than 10:30 ET; market orders in first 5 min underestimate cost by ~10 bps. | Friction profile is constant | ~30 LOC |
| **Cycle-phase-aware bandit prior decay** | On regime transition, multiply (α,β) × 0.3 for affected strategies. Stops "winning in mid_cycle" priors from poisoning late_cycle Thompson. | cycle_phase available but not wired to bandit | ~80 LOC |
| **Post-trade factor attribution** | Decompose every closed trade into market beta + Fama-French 5-factor + sector + idiosyncratic alpha. Answers "are we generating alpha or just long the market?" | Not implemented | ~250 LOC |
| **3-tier drawdown throttle** | 5% DD → cut sizing 25%; 10% → cut 50%; 15% → halt new opens. Academic proof (`arxiv:1710.01503`) bounds max-DD. | Risk governor has hooks; levels not formalized | ~40 LOC |
| **Beta-adjusted exposure cap** | Rolling-60d beta to SPY per position; portfolio beta-adjusted net capped at ±50% NAV. Catches "5 longs all on momentum factor" blindness. | No correlation cap; raw notional only | ~150 LOC |
| **ADWIN on portfolio P&L distribution** | Complement to per-strategy PH; catches variance regime change PH misses. River library, one import. | Page-Hinkley only | ~100 LOC |
| **Per-sector cap (±20% NAV)** | Map every position to sector ETF; sum exposure; gate new opens. Cheap correlation-blindness fix. | Heat caps per strategy only, not per sector | ~100 LOC |
| **AUTO_TRADER_MANDATE.md doc + memory ingest** | Codifies risk budget, sleeve allocation, success metrics as procedural memory (importance 95). Auditable + bandit objective. | Mandate lives only in policy.json notes field | 1 doc + ~10 LOC |
| **Monthly portfolio review cron** | 1st-of-month: strategy scorecard (Calmar/Sortino/Sharpe/alpha decomp per sleeve), retire/explore recommendations. Closes "who's looking at this weekly?" gap. | Only EOD daily summary | ~300 LOC |
| **Emergency stop endpoint** | `POST /auto-trader/emergency-stop` — closes all positions + disables bot + requires manual resume. | Pause/resume only; no position flatten | ~50 LOC |
| **GOAT/BRAVO scanner auto-emit** | Scanners should emit via record_emission() the same way quant_scanners does. | Wired in `scanner.py` (Wave 14S) but no chains tagged "goat"/"bravo" today — not reaching loop | ~20 LOC + diagnosis |

### Failure modes the literature flags that we should preempt
1. **Look-ahead bias** — fix: hard timestamp gate on signal_time < decision_time
2. **Survivorship bias** — fix: point-in-time universe
3. **Overfit recipes** — fix: max 5 params per recipe, walk-forward CV, Lopez-de-Prado purged-CV
4. **Leverage creep** — fix: hard leverage cap independent of Kelly/vol-target
5. **Correlation blindness** — covered by per-sector cap + beta-adjusted exposure (above)
6. **Regime hangover** — covered by cycle_phase-aware bandit prior decay (above)
7. **Fee/slippage underestimation** — covered by intraday friction multiplier (above)
8. **Paper-vs-live psychology** — fix: 10-25-50-100% capital ramp on transition
9. **Single-source fragility** — already covered by Wave 14K Phase 8 circuit breakers
10. **Silent data-quality bugs** — covered by pre-trade sanity gate (above)

---

## Part 3 — Wave 14U Ranked Backlog

Top 12 ordered by `(impact × cheapness × closes-known-gap)`:

### Hotfix tier (ship today, blocks production)
1. **HOTFIX A — drawdown NAV staleness guard** — fix dd=-100% root cause. ~30 LOC.
2. **HOTFIX B — registry-in-governor-path** — call `normalize_strategy_via_registry()` before governor in loop.py. Fixes 38% of today's rejects. ~5 LOC.
3. **HOTFIX C — diagnose GOAT/BRAVO scanner emit non-firing** — verify record_emission calls in scanner.py are reaching trade_idea_tracker. Investigation + likely small wire-up fix.

### High-leverage upgrades (Wave 14U-1 ship this week)
4. **Pre-trade sanity gate** — 4-check filter before risk governor. ~50 LOC. Closes the entire "stale data / hallucinated ticker" failure class.
5. **AUTO_TRADER_MANDATE.md + procedural memory ingest** — explicit mandate doc, ingested as importance-95 procedural memory. ~1 doc + 10 LOC.
6. **Intraday friction multiplier** — extend FrictionProfile with time-of-day multiplier (1.5x first/last 5 min). ~30 LOC. Biggest paper-to-live realism win.
7. **Emergency stop endpoint** — `POST /auto-trader/emergency-stop` flattens all + disables. ~50 LOC.
8. **3-tier drawdown throttle formalization** — 5/10/15% step-down. Risk governor already has hooks. ~40 LOC.

### Mid-leverage upgrades (Wave 14U-2 ship next week)
9. **Cycle-phase-aware bandit prior decay** — wire cycle_phase transition → multiply (α,β) × 0.3 for regime-sensitive strategies. ~80 LOC.
10. **Per-sector cap (±20% NAV)** — sector ETF exposure aggregation + gate. ~100 LOC.
11. **ADWIN on portfolio P&L distribution** — complement to PH; River library import. ~100 LOC.

### High-effort upgrades (Wave 14U-3 ship sprint)
12. **Post-trade factor attribution** — Fama-French 5-factor + sector decomposition per closed trade. ~250 LOC.
13. **Beta-adjusted exposure cap** — rolling-60d beta to SPY per position, ±50% NAV cap. ~150 LOC.
14. **Monthly portfolio review cron** — 1st-of-month strategy scorecard + retire/explore decisions. ~300 LOC.

---

## Part 4 — Schedule architecture (current vs recommended)

| Cron task | Current cadence | Recommended | Notes |
|---|---|---|---|
| `ncl-auto-trader-loop` | 60s market / 300s off | ✅ keep | Industry standard |
| `ncl-auto-trader-prices` | 30s market / 300s off | ✅ keep | Industry standard |
| `ncl-auto-trader-quant-scan` | 5 min | ✅ keep | Don't over-poll |
| `ncl-auto-trader-scout` | 5 min | ✅ keep | |
| `ncl-auto-trader-eod` | daily 18:00 ET | ✅ keep | |
| **NEW: `ncl-auto-trader-weekly`** | — | Sun 18:00 ET | Loss-cluster analysis, research topic generation, graduation gate review |
| **NEW: `ncl-auto-trader-monthly`** | — | 1st of month 06:00 ET | Strategy scorecard, retire/explore recommendations, prior decay |
| **NEW: `ncl-auto-trader-quarterly`** | — | 1st of quarter 06:00 ET | HMM re-fit, factor exposure re-estimate, friction profile reset |

---

## Part 5 — Mandate framing (recommended doc structure)

Currently the mandate lives in `data/portfolio/auto_trader/policy.json` notes field: "Hedge-fund-manager-in-training experiment. Match live NAV $36,149 CAD. Risk per trade: 5%. Max 8 opens/day, 2/tick. Stocks + options allowed."

The institutional template (per Resonanz, CME, NYC Comptroller) needs these sections:

```markdown
# Auto-Trader Mandate v1.0

## Strategy description
1-paragraph plain English: what edge, what universe, what holding period.

## Risk budget
- Target annualized vol: 15%
- Max drawdown: 15%
- Sharpe target: 1.0+
- Calmar target: 0.7+

## Sleeve allocation
- 30% trend (GOAT)
- 25% swing (BRAVO)
- 15% stat-arb (pairs)
- 10% mean reversion
- 10% PEAD
- 10% factor / whale flow / crypto carry / polymarket

## Universe
Explicit ticker list or filter rule (e.g. "US large-cap ex-financials, ADV>$50M")

## Stop-out triggers
- NAV drops 15% from peak → 50% deallocation
- NAV drops 20% from peak → 100% halt + 30d cooldown

## Success metrics
- Net-of-fees Sharpe > 1
- Max DD < 15%
- Alpha (factor-adjusted) > 5%/yr

## Governance
- Param changes require operator approval via REST POST /auto-trader/policy
- Kill switch: POST /auto-trader/emergency-stop
- Audit cadence: weekly cron + manual on-demand
```

Save to `docs/AUTO_TRADER_MANDATE.md`, ingest as procedural memory at importance 95, cite mandate version in every reasoning chain.

---

## Part 6 — Further reading

See full source list at `outputs/auto_trader_research_notes.md` Section (c). Top 5 for deep-dive:

1. **López de Prado** — *Advances in Financial Machine Learning* — validation, triple-barrier, purged-CV
2. **Carver** — *Systematic Trading* + qoppac.blogspot.com — vol-targeting, diversification multiplier
3. **TradingAgents** — arxiv:2412.20138 — LLM-agent trading architecture
4. **FAITH benchmark** — arxiv:2508.05201 — LLM-in-loop hallucination guards
5. **CME — Evaluating CTAs** — industry standard for graduation bars

---

## Summary for NATRIX

**The agent is architecturally sound.** All major feedback loops are wired and align with 2024-26 best practice. The Wave 14K stack (Beta-Bernoulli + Thompson, Page-Hinkley, SHAP, graduation gate, friction profile, risk governor, reasoning chains) is what serious shops build.

**What's blocking the agent right now** (2 bugs, hotfix today):
1. drawdown NAV staleness → dd=-100% → 26/42 rejects today
2. strategy registry not wired into governor hot path → pairs_stat_arb → "unknown" bucket → 16/42 rejects today

**What would 10x the agent's edge** (Wave 14U, ship this week):
1. Pre-trade sanity gate (catches stale data / hallucinated tickers)
2. Explicit mandate doc + procedural memory ingest
3. Intraday friction multiplier (biggest paper-to-live realism win)
4. Emergency stop endpoint (manual kill switch)
5. 3-tier drawdown throttle formalization

**What would make the agent institutional-grade** (Wave 14U-2/-3, multi-week):
- Cycle-phase-aware bandit prior decay
- Post-trade Fama-French factor attribution
- Beta-adjusted exposure cap
- Per-sector cap
- Monthly portfolio review cron

The agent has a clear mandate, is self-learning, self-analyzing, self-reflecting, and self-functioning. It just needs 2 bugfixes and ~5 high-leverage additions to be ready for serious paper-trading evaluation (and eventually graduation toward live).
