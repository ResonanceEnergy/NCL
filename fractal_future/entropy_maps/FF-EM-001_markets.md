# ENTROPY MAP — FF-EM-001: Markets (AAC Mixed Book)

- Domain: markets
- System: AAC mixed book (equities/options + crypto)

## Entropy Ingress (Where Disorder Enters)
- Volatility spikes and vol-of-vol jumps
- Correlation coupling (diversification failure)
- Liquidity shocks (gaps, slippage, wick cascades)
- Regime drift (non-stationarity / parameter decay)
- Information shocks (macro events, earnings, headlines)
- Execution friction (fees, spreads, latency)

## Accumulation Zones (Where It Piles Up)
- Overlapping strategy exposure (hidden coupling)
- Unbounded leverage / unbounded sizing rules
- Too many active strategies without isolation
- Overfitting and parameter sensitivity (backtest ≠ reality)
- No regime filter (signal traded in wrong phase)
- Poor kill-switch discipline (slow response to regime change)

## Dissipation Paths (Where It Exits Safely)
- Exposure throttles when entropy regime rises (E-level upshift)
- Correlation caps (reduce gross exposure when cluster score high)
- Liquidity shock pause rules (avoid tight stops during wicks/gaps)
- Circuit breakers: daily/weekly drawdown valves
- Cooldown periods after kill switch triggers (pause + diagnose + re-validate)

## Budgets (Thresholds)
- Portfolio max DD: __%
- Max daily loss: __%
- Max weekly loss: __%
- Max allowed entropy regime: E__
- Correlation cluster ceiling: __
- Liquidity shock ceiling (wick/gap index): __

## Valves (Explicit Mechanisms)
| Valve | Trigger | Action |
|-------|---------|--------|
| V1 | Entropy regime +1 level | Reduce exposure by ___% |
| V2 | Correlation cluster breach | Cap gross exposure at ___% |
| V3 | Liquidity shock proxy | Pause tight-stop cells for ___ sessions |
| V4 | DD breach | Portfolio kill switch + cooldown |
| V5 | Vol spike > ___th percentile | Halve position sizing |

## Failure Modes (What Fails First)
- Tight stop strategies during liquidity shock
- Mean reversion during trend emergence
- Trend continuation during contagion chop
- Any strategy without regime filter during E4+

## Blast Radius (Local vs Cascading)
- **Goal:** Fail-local by strategy cell
- **Prevention:** Allocation caps + correlation caps + portfolio kill switch
- **Worst case:** Portfolio-level if caps are not enforced

## Actions (What to Change Next)
1. Implement entropy regime card weekly (E1–E5 scoreboard)
2. Apply strategy cell allocation caps + kill switch rules
3. Backtest correlation cluster throttle effect (FF_AAC_BT_002)
