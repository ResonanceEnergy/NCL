# Stage 02: Extraction

Parse and extract key findings, claims, methodologies, and data from sources.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 01 | `/Projects/NCL/research/sources/{topic}_{date}.json` | Source catalog + raw texts | Extraction input list |

## Process

1. For each source: parse abstract/summary
2. Extract claims (assertion + evidence strength)
3. Extract methods (experimental design, parameters)
4. Extract quantitative data (results, tables, figures)
5. Tag domain, confidence level, publication status

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Extraction Summary | `/Projects/NCL/research/extractions/{uuid}.json` | JSON (structured claims) |
| Evidence Index | `/Projects/NCL/research/evidence_{topic}_{date}.tsv` | TSV (claim, source, strength) |
