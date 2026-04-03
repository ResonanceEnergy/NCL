# Stage 01: Episodic Intake

Ingest raw observations (feedback, research, intelligence, decisions) into memory.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Feedback | `/Projects/NCL/feedback/reports/` | NCC, BRS, AAC reports | Operational observations |
| Research | `/Projects/NCL/research/synthesis_*` | Research syntheses | Domain knowledge updates |
| Intelligence | `/Projects/NCL/intelligence/insights/` | Daily intelligence insights | External signal observations |
| Decisions | `/Projects/NCL/mandates/approved/` | Mandate approvals, changes | Decision recording |

## Process

1. Detect new event in any source (file modification, API hook)
2. Extract observation data (what, when, from whom, context)
3. Tag observation type (feedback, research, signal, decision)
4. Assign unique episode ID and timestamp
5. Store raw episode with metadata

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Episode Log | `/Projects/NCL/memory/episodic/episodes_{date}.jsonl` | JSONL |
| Intake Manifest | `/Projects/NCL/memory/intake_{date}.json` | JSON (count, sources) |
