# Stage 01: Report Intake

Receive structured feedback reports from NCC, BRS, AAC pillars.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| NCC | `/Projects/NCC-Doctrine/reports/` | Execution truth, blockers, friction | Operational feedback |
| BRS | `/Projects/BRS-Context/reports/` | Revenue data, conversions, market fit | Economic signals |
| AAC | `/Projects/AAC-Context/reports/` | P&L, trades, capital performance | Financial intelligence |

## Process

1. Monitor feedback directories for new reports (polling + file hooks)
2. Validate report schema (required: pillar, timestamp, metrics, summary)
3. Extract structured data (KPIs, blockers, anomalies)
4. Assign report ID and intake timestamp
5. Store validated report with metadata

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Intake Log | `/Projects/NCL/feedback/intake_{date}.jsonl` | JSONL (report metadata) |
| Report Archive | `/Projects/NCL/feedback/reports/{pillar}/{uuid}.json` | JSON (validated report) |
