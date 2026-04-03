# Stage 02: Validation

Claude-validated synthesis of feedback signals with confidence scoring.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 01 | `/Projects/NCL/feedback/intake_{date}.jsonl` | All received reports | Validation input |
| Context | `/Projects/NCL/mandates/approved/` | Active mandates | Mandate-feedback mapping |

## Process

1. Load all reports from intake log
2. For each report: validate claim structure (assertion + evidence)
3. Cross-check claims against mandate KPIs (relevant? contradictory?)
4. Score confidence (0-100) based on data quality and source authority
5. Produce synthesis summary with confidence ranges

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Validation Summary | `/Projects/NCL/feedback/validation_{date}.md` | Markdown (claims + confidence) |
| Signal Matrix | `/Projects/NCL/feedback/signal_matrix_{date}.json` | JSON (claim × confidence grid) |
