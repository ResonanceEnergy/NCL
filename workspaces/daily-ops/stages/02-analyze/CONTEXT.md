# Daily Analyze

Detect patterns, anomalies, and actionable signals from the daily collection.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../01-collect/output/` | Full file | Daily collection manifest |
| Historical data | `../../../data/derived/` | Last 7 days | Trend baseline |

## Process

1. Read the daily collection from 01-collect/output/
2. Group events by category and source
3. Detect frequency anomalies (events above/below normal rates)
4. Identify recurring patterns across the 7-day window
5. Flag actionable items (deadlines, escalations, opportunities)
6. Write analysis results to output/

## Checkpoints

| After Step | Agent Presents | Human Decides |
|------------|---------------|---------------|
| 5 | Flagged actionable items with priority | Which items to act on |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Analysis report | output/[date]-analysis.md | Markdown with flags |
