# Entropy Budgets — Standard (v1.0)

## Definition
An entropy budget is the maximum tolerable rate of disorder before performance degrades or failure risk becomes unacceptable.

---

## Budget Types

### Human Entropy Budget
- Attention depletion threshold
- Stress load threshold
- Context-switch ceiling
- Recovery minimums (sleep/rest)
- Max active tracks: 2 (default), 3 (temporary), >3 = overload

### System Entropy Budget (Software/Agents)
- Acceptable error rate
- Acceptable drift rate
- Max rework ratio
- Max unresolved tasks backlog
- Dependency churn ceiling

### Market/Portfolio Entropy Budget (AAC)
- Max realized volatility tolerated
- Max correlation cluster tolerated
- Max drawdown per cell and portfolio
- Liquidity shock thresholds

### Organizational Entropy Budget
- Max policy sprawl (number of active rules)
- Max decision coupling (dependencies per decision)
- Max governance latency (time to decision)
- Max conflicting directives

---

## Budget Rule
> If entropy exceeds budget, the system MUST automatically trigger valves: throttle, reset, isolate, or prune.

Budgets are meaningless without valves and enforcement.

---

## Entropy Valves (Standard Set)
| Valve | Action |
|-------|--------|
| V1: Throttle | Reduce active work / exposure / parallelism |
| V2: Reset | Force synthesis / summary / clean slate |
| V3: Isolate | Contain failure to local scope |
| V4: Prune | Remove duplicates / stale / low-value items |
| V5: Circuit Breaker | Full stop + cooldown + diagnosis |
| V6: Cooldown | Pause before resumption after breach |

---

## Measurement
Track entropy indicators weekly:
- Drift rate
- Rework ratio
- Contradiction count
- Coupling index
- Backlog delta
- Decision latency

Budget state: **WITHIN** / **APPROACHING** / **EXCEEDED**
