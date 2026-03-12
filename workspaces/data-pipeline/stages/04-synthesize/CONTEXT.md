# Data Synthesize

Integrate processed insights into the knowledge graph and derived data store.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../03-process/output/` | Full file | Processed insights |
| Derived store | `../../../data/derived/` | Full directory | Existing knowledge |
| Event log | `../../../data/event_log/` | Recent entries | Historical context |

## Process

1. Read processed insights from 03-process/output/
2. Match insights against existing derived data for deduplication
3. Create bi-directional links between related insights (digital garden pattern)
4. Update the derived data store with new entries
5. Append synthesis log to data/event_log/
6. Write the synthesis report to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| No duplicates | New entries do not duplicate existing derived data |
| Links valid | All bi-directional links point to existing entries |
| Logged | Synthesis event written to event_log |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Synthesis report | output/[date]-synthesis.md | Markdown summary |
