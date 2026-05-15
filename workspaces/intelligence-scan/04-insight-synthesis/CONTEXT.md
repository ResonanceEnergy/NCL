# Stage 04: Insight Synthesis

Compress top signals into 3-5 key insights with actionable implications.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 03 | `/dev/NCL/intelligence/scored_{timestamp}.json` | Top 20 signals (score > 60) | Insight source |

## Process

1. Group top signals by theme (geopolitics, tech, finance, culture)
2. For each theme: extract common pattern or trend
3. Synthesize insight statement (1-2 sentences, action-oriented)
4. Score confidence (0-100) based on source consistency
5. Add implications and recommended actions

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Insight Report | `/dev/NCL/intelligence/insights/{date}_report.md` | Markdown |
| Insight JSON | `/dev/NCL/intelligence/insights/{date}.json` | JSON (structured insights) |

## Checkpoints

- Each insight backed by minimum 2 independent signals
- Confidence scores justified (consistency count, trust scores)
- Implications clearly derived from insight statement

## Audit

- Insight generation timestamp
- Source signals cited
- Confidence derivation (formula + values)
- Synthesis model and parameters
