# Intelligence Scan Workspace

Awarebot-FPC - scan X/YouTube/Reddit, extract signals, score importance, synthesize insights.

## Stages

| Stage | Name | Purpose |
|-------|------|---------|
| 01 | Source Ingest | Fetch feeds from X, YouTube, Reddit APIs |
| 02 | Signal Extraction | Identify actionable signals (trends, anomalies, events) |
| 03 | Importance Scoring | Score 0-100 using multi-factor formula |
| 04 | Insight Synthesis | Compress signals into 3-5 key insights |
| 05 | Distribution | Route insights to relevant NCL/NCC modules |

## Key Artifacts

- **Input**: Feed configurations, source subscriptions
- **Intermediate**: Raw signal log, scored signals, insight draft
- **Output**: Daily insight report (routed to decision makers)

## Authority

Awarebot-FPC autonomously executes stages 01-04. NCL reviews and routes stage 05 outputs.

## Execution Model

Stages 01-02 run hourly (continuous feed). Stage 03 continuous. Stage 04 aggregates hourly → daily report at 06:00 UTC.

## Storage

- Raw feeds: `/Projects/NCL/intelligence/raw/{source}/`
- Signals: `/Projects/NCL/intelligence/signals.log`
- Insights: `/Projects/NCL/intelligence/insights/{date}/`
