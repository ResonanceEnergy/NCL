# Stage 02: Semantic Extraction

Extract MemUnits (atomic facts) with source, confidence, and temporal metadata.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 01 | `/Projects/NCL/memory/episodic/episodes_{date}.jsonl` | All episodes | MemUnit extraction source |

## Process

1. Parse episode content (research abstract, feedback claim, insight statement)
2. Extract atomic facts (distinct, indivisible assertions)
3. Record source (observation type, original file, authority)
4. Assign confidence (0-100 based on source type and evidence)
5. Add temporal metadata (observation date, relevance window)

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| MemUnits | `/Projects/NCL/memory/units/{uuid}.yaml` | YAML (fact + metadata) |
| Extraction Log | `/Projects/NCL/memory/extraction_{date}.json` | JSON (count, confidence distribution) |
