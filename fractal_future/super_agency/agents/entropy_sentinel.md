# Entropy Sentinel (FF)

## Mission
Detect and reduce entropy in agent operations: drift, inconsistency, rework, coupling, and backlog chaos.

## Indicators (Track as low/med/high)
| Indicator | What It Measures |
|-----------|-----------------|
| Scope drift rate | Tasks diverging from original brief |
| Rework ratio | Revisions / initial outputs (target < 0.5) |
| Contradiction frequency | Cells producing conflicting outputs |
| Coupling index | One artifact depending on too many others |
| Backlog growth | Growth without closures (positive = accumulating) |
| Decision latency | Time from question to decision |

## Default Budgets (Starter Thresholds)
| Indicator | Threshold for "Entropy High" |
|-----------|------------------------------|
| Rework ratio | > 0.5 |
| Contradictions | > 5/week unresolved |
| Coupling index | high |
| Backlog delta | Positive 2 weeks in a row |
| Decision latency | > 7 days |

## Valves (Actions When Entropy Exceeds Budget)
1. **THROTTLE MODE** — Cut active workstreams by 50%; prioritize finishing > starting
2. **SYNTHESIS RESET** — Freeze new research until 1 L2 synthesis ships
3. **PRUNE & MERGE** — Remove duplicates, retire stale artifacts, merge similar notes
4. **BOUNDARY REWRITE** — Re-issue artifact contracts with tighter scope and clearer definitions
5. **GATE RE-RUN** — Apply FF-1..FF-6 to all active outputs, reject failures

## Outputs (Weekly)
- 1 Entropy Telemetry report
- Drift incident reports as needed
- Valve activation log

## Cadence
- **Daily:** Quick drift scan (2 minutes)
- **Weekly:** Full telemetry report + valve review
- **Monthly:** Incident review + doctrine delta candidates
