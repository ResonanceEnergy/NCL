# AAC — Entropy Regimes (v1.0)

## Market Entropy (Operational)
In AAC, entropy manifests as:
- **Volatility** — energy dispersion / price disorder
- **Correlation coupling** — diversification failure
- **Liquidity fragility** — gaps, slippage, wick cascades
- **Regime drift** — non-stationarity / parameter decay
- **Tail risk** — rare shocks with outsized impact

---

## Entropy Regime Scale (E1–E5)

| Level | Name | Description |
|-------|------|-------------|
| E1 | Calm / Compression | Low vol, tight ranges, orderly moves |
| E2 | Normal / Structured | Average vol, predictable regimes, clean signals |
| E3 | Elevated / Unstable | Rising vol, correlation shifts, regime transitions |
| E4 | Shock / Contagion | High vol, correlation spikes, liquidity gaps |
| E5 | Disorder / Liquidation | Extreme vol, cascade failures, market-wide stress |

---

## Regime Detection Inputs (Starter)
- Realized vol / ATR percentile
- Vol-of-vol
- Correlation cluster score
- Wick/gap frequency (liquidity proxy)
- Trend structure stability

---

## Rules
1. **Strategy selection and sizing must be entropy-regime aware.**
2. When entropy regime rises → leverage and exposure must fall automatically.
3. When entropy regime ≥ E4 → only defensive/hedging strategies permitted.
4. Kill switches trigger at defined E-level thresholds per strategy cell.

---

## Regime Types (Starter Taxonomy — Mixed Book)

### Regime 1: TREND / EXPANSION
- Directional structure dominates (HH/HL or LH/LL)
- Breakouts follow through; pullbacks are bought/sold with continuation
- Feature votes: strong trend on 2+ timeframes, moderate vol, stable gaps
- Cells favored: trend, momentum, breakout retests
- Cells throttled: pure mean reversion fades

### Regime 2: RANGE / MEAN-REVERSION
- Price oscillates within defined band; breakouts fail
- Mean reversion dominates at edges; midline acts as gravity
- Feature votes: repeated rejections at boundaries, stable/compressing vol
- Cells favored: mean reversion, range scalps
- Cells throttled: trend continuation breakouts

### Regime 3: VOLATILITY EXPANSION (RISK-OFF / PANIC)
- Realized vol and intrabar range jump materially above baseline
- Large candles, frequent gaps, impulsive liquidation moves
- Correlation rises sharply ("everything moves together")
- Cells favored: vol hedges, defensive
- Cells throttled: leverage-heavy trend chasing

### Regime 4: VOLATILITY COMPRESSION (CALM / COIL)
- Realized vol drops; ranges tighten; coiling structures appear
- Breakout probability increases but direction uncertain pre-break
- Cells favored: breakout-prep, straddle logic, level mapping
- Cells throttled: vol-chasing systems

### Regime 5: LIQUIDITY SHOCK / GAP RISK
- Discontinuous price moves; liquidity thins; slippage rises
- Levels break without tradeable retests
- Cells favored: risk-control, hedging, reduced sizing
- Cells throttled: tight-stop strategies, high-frequency scalps

### Regime 6: CORRELATION SPIKE / CONTAGION
- Cross-asset correlation rises materially
- Diversification fails; portfolio behaves like one bet
- Cells favored: hedged structures, reduced gross exposure
- Cells throttled: multi-name diversification assumptions
