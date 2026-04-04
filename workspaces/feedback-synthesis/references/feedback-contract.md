# NCL Feedback Contract

## Purpose
Defines the schema and rules for how downstream pillars (NCC, BRS, AAC) report feedback to NCL.

## Core Rules

1. **No raw data**: Feedback enters NCL only through Claude-validated synthesis. Pillar reports are structured JSON — never logs, metrics dumps, or unprocessed API responses.

2. **Structured reports only**: Each pillar produces reports conforming to its schema (see pillar report README files in `ncc-reports/`, `brs-reports/`, `aac-reports/`).

3. **Cross-validation required**: Before feedback reaches mandate generation, it must pass through the synthesis pipeline which cross-references reports from all three pillars for consistency.

4. **Mandate adjustment threshold**: Only synthesis findings with confidence >= 0.8 and impact != "neutral" trigger mandate review recommendations.

5. **Escalation path**: CRITICAL findings bypass normal synthesis schedule and go directly to NCL for immediate mandate review.

## Report Frequency

| Pillar | Daily | Weekly | On-Event |
|--------|-------|--------|----------|
| NCC    | Health check | Full execution review | Deployment failure |
| BRS    | Revenue snapshot | Pipeline review | Deal closure |
| AAC    | Portfolio snapshot | Strategy review | Doctrine state change |

## Versioning

This contract is versioned. Current version: 1.0.0. Changes require NCL mandate approval.
