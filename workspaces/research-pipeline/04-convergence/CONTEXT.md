# Stage 04: Convergence

Detect cross-domain patterns and signal convergence (UNI intelligence output).

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 03 | `/dev/NCL/research/synthesis_{topic}_{date}.md` | All topic syntheses | Convergence detection input |
| Index | `/dev/NCL/research/convergence_index.yaml` | Pattern registry | Known convergence signals |

## Process

1. Scan synthesis across all active topics
2. Identify shared claims, contradictions, emerging patterns
3. Score convergence strength (topic overlap, evidence density)
4. Flag novel patterns not in convergence index
5. Produce convergence report with implications

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Convergence Report | `/dev/NCL/research/convergence/{date}_report.md` | Markdown |
| Signal Log | `/dev/NCL/research/convergence_signals.log` | JSONL |

## Checkpoints

- Pattern scoring algorithm reproducible
- Novel signals validated by multi-source consensus
- Implications section clear and actionable

## Audit

- Cross-reference count for each pattern
- Timestamp of signal first detection
- Source domains contributing to pattern
