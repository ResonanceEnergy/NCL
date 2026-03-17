# AAC Portfolio Entropy Budget + Valves — FF_AAC_RISK_000

## Portfolio Budget
- Max daily loss: __%
- Max weekly loss: __%
- Max drawdown: __%
- Max leverage: __x
- Max correlation cluster score: __
- Max allowed entropy regime: E__

## Valves (Automatic)
| Valve | Trigger | Action |
|-------|---------|--------|
| V1 | Entropy regime +1 level | Reduce exposure by ___% |
| V2 | Correlation cluster breach | Cap gross exposure at ___% |
| V3 | Liquidity shock proxy | Pause tight-stop cells for ___ sessions |
| V4 | Drawdown breach | Portfolio kill switch + cooldown |
| V5 | Vol > ___th percentile | Halve position sizing |

## Recovery Protocol
1. Pause all execution
2. Diagnose (regime mismatch / execution error / signal drift)
3. Re-validate (multi-scale standard)
4. Resume with reduced size (50% for ___ sessions)

## Review Cadence
- Daily: quick posture check
- Weekly: full regime map + valve audit
- Monthly: budget review + threshold adjustment if warranted
