# Stage 03: Consolidation

Merge related MemUnits, resolve conflicts, build consolidated index.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| MemUnits | `/Projects/NCL/memory/units/` | All historical units | Consolidation source |
| New Units | `/Projects/NCL/memory/units/{uuid}.yaml` | Today's extractions | Incremental update |

## Process

1. Load all existing MemUnits from consolidated index
2. Load new MemUnits from stage 02
3. Detect duplicates (semantic similarity > 0.8)
4. Merge duplicates (keep higher confidence, merge sources)
5. Detect conflicts (contradicting assertions) - flag for review
6. Rebuild consolidated index

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Consolidated Index | `/Projects/NCL/memory/index_consolidated.json` | JSON (merged units + dedup map) |
| Conflict Log | `/Projects/NCL/memory/conflicts_{date}.json` | JSON (contradictions flagged) |

## Checkpoints

- Duplicate detection threshold justified (cosine > 0.8)
- Merge rules applied consistently
- Conflict resolution documented

## Audit

- Merge count (units consolidated)
- Conflict count and resolution status
- Consolidation timestamp and version
