# Stage 03: Analysis

Cross-reference findings, validate assertions, build synthesis matrix.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 02 | `/dev/NCL/research/evidence_{topic}_{date}.tsv` | All extracted claims | Cross-ref foundation |
| Memory | `/dev/NCL/memory/units/` | Historical findings | Prior art check |

## Process

1. Build claim matrix (claim ID, sources citing it, confidence)
2. Identify claim conflicts or supports
3. Cross-reference with prior research memory
4. Score assertion strength (evidence count × quality)
5. Produce synthesis matrix

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Claim Matrix | `/dev/NCL/research/matrix_{topic}_{date}.json` | JSON |
| Synthesis | `/dev/NCL/research/synthesis_{topic}_{date}.md` | Markdown |
