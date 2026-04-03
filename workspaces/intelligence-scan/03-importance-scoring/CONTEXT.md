# Stage 03: Importance Scoring

Score signals 0-100 using multi-factor formula and contextual relevance.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 02 | `/Projects/NCL/intelligence/signals.log` | All extracted signals | Scoring input |
| Context | `/Projects/NCL/mandates/approved/` | Active mandates | Relevance weight factors |

## Process

1. For each signal: extract features (engagement, recency, source authority)
2. Calculate base score: (engagement × 0.3) + (trend_velocity × 0.3) + (source_trust × 0.4)
3. Apply mandate relevance multiplier (1.0-2.0x boost if relevant to active mandates)
4. Cap at 100, floor at 1 (exclude zero-score noise)
5. Sort and annotate top signals

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Scored Signals | `/Projects/NCL/intelligence/scored_{timestamp}.json` | JSON (signal + score) |
| Score Audit | `/Projects/NCL/intelligence/score_audit_{timestamp}.tsv` | TSV (formula trace) |

## Checkpoints

- Scoring formula reproducible and logged
- Top 10 signals manually validated for relevance
- Edge cases (zero engagement, no metadata) handled

## Audit

- Score derivation for each signal (formula values)
- Mandate relevance multiplier applied (y/n)
- Timestamp and scorer version
