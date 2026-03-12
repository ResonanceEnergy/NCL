# Daily Brief

Generate the daily intelligence brief from analysis results.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../02-analyze/output/` | Full file | Analysis with flags |
| Collection | `../01-collect/output/` | Summary section | Data volume context |
| Doctrine | `../../../docs/STRATEGIC_DOCTRINE.md` | "Priorities" | Strategic alignment |

## Process

1. Read analysis results from 02-analyze/output/
2. Structure the brief: executive summary, key patterns, flagged items, metrics
3. Prioritize flagged items against strategic doctrine priorities
4. Generate recommended actions for each flagged item
5. Write the daily brief to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| Has summary | Executive summary is under 200 words |
| Actions specific | Each recommended action has a clear next step |
| Priorities aligned | Flagged items reference strategic doctrine |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Daily brief | output/[date]-daily-brief.md | Markdown intelligence report |
