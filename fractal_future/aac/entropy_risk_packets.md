# AAC — Entropy Risk Packets (v1.0)

## Purpose
Convert entropy into enforceable constraints. Every strategy cell and the portfolio as a whole must have an entropy risk packet.

---

## Portfolio Entropy Budget
- Max daily loss: __%
- Max weekly loss: __%
- Max drawdown: __%
- Max leverage: __x
- Max correlation cluster score: __
- Max allowed entropy regime: E__
- Liquidity shock ceiling: __

## Portfolio Valves (Mandatory)
| Valve | Trigger | Action |
|-------|---------|--------|
| V1 | Entropy regime rises by 1 level | Reduce exposure by ___% |
| V2 | Correlation cluster breaches threshold | Cap total gross exposure at ___% |
| V3 | Liquidity shock proxy triggers | Pause tight-stop cells for ___ sessions |
| V4 | Drawdown breaches ___% | Portfolio kill switch + cooldown |
| V5 | Vol spike > ___th percentile | Halve position sizing |

## Recovery Protocol (After Kill Switch)
1. Pause all execution
2. Diagnose: regime mismatch? execution error? signal drift?
3. Re-validate: multi-scale validation standard
4. Resume with reduced size (50% for ___ sessions)

---

## Strategy Cell Entropy Budget (Template)
- Cell name:
- Allocation cap: __% of portfolio
- Max cell drawdown: __%
- Max loss streak before throttle: __
- Max allowed entropy regime: E__ (typically E1–E3; throttle above)
- Kill switch conditions:

## Cell Valves
- Regime mismatch throttle: reduce size by ___% or pause
- Cooldown after kill switch: ___ sessions
- Require retest confirmation when entropy ≥ E3

---

## Golden Rules
1. No cell may exceed its entropy budget.
2. No strategy is allowed to threaten portfolio survivability.
3. Failure must be local, informative, and containable.
4. Kill switches are non-negotiable; recovery follows protocol.
