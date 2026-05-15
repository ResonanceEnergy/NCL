# Stage 03: Pattern Detection

Identify recurring themes and anomalies across validated reports.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 02 | `/dev/NCL/feedback/signal_matrix_{date}.json` | All validated signals | Pattern detection source |
| History | `/dev/NCL/feedback/patterns_{date-7}*.json` | Prior week patterns | Temporal trend detection |

## Process

1. Build signal occurrence matrix (signal × report count)
2. Identify high-frequency signals (>50% of reports mention)
3. Detect temporal trends (signal frequency increasing/decreasing)
4. Extract anomalies (unexpected combinations, new signals)
5. Score pattern strength (frequency + consistency)

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Pattern Report | `/dev/NCL/feedback/patterns_{date}.md` | Markdown (patterns + trends) |
| Pattern Matrix | `/dev/NCL/feedback/patterns_{date}.json` | JSON (signal, frequency, trend) |

## Checkpoints

- Frequency threshold justified (> 50% occurrence)
- Trend detection validated across minimum 2 time periods
- Anomaly detection tuned to signal noise ratio

## Audit

- Pattern detection timestamp
- Signal frequency distribution
- Temporal trend calculation (slope, significance)
