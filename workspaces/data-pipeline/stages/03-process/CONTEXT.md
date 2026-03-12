# Data Process

Apply CODE methodology (Capture, Organize, Distill, Express) to validated events.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../02-validate/output/` | Full file | Validated events |
| Doctrine | `../../../docs/CREATOR_DOCTRINE.md` | "CODE Methodology" | Processing rules |
| Derived store | `../../../data/derived/` | Recent entries | Existing processed data |

## Process

1. Read validated events from 02-validate/output/
2. **Capture**: Tag each event with source, timestamp, context metadata
3. **Organize**: Group events by type, theme, and temporal proximity
4. **Distill**: Extract key insights, patterns, and actionable items from each group
5. **Express**: Format distilled insights as atomic notes (Zettelkasten-style)
6. Write processed insights to output/

## Checkpoints

| After Step | Agent Presents | Human Decides |
|------------|---------------|---------------|
| 4 | Extracted patterns and proposed groupings | Which patterns to keep |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Processed insights | output/[date]-insights.md | Markdown atomic notes |
| Pattern summary | output/[date]-patterns.json | JSON pattern data |
