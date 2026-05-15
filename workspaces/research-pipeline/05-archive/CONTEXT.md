# Stage 05: Archive

Store findings in memory system and convergence index for future recall.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 04 | `/dev/NCL/research/convergence/{date}_report.md` | Final convergence output | Archive source |
| Stage 03 | `/dev/NCL/research/synthesis_{topic}_{date}.md` | Topic syntheses | Semantic extraction |

## Process

1. Parse convergence report and syntheses
2. Extract MemUnits (atomic facts + source + confidence)
3. Consolidate with existing memory units (merge related)
4. Apply decay reinforcement (boost cited units)
5. Rebuild convergence index and retrieval indices

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| MemUnits | `/dev/NCL/memory/units/{uuid}.yaml` | YAML (fact + meta) |
| Index | `/dev/NCL/memory/index_convergence.json` | JSON (searchable) |
| Decay Map | `/dev/NCL/memory/decay_{date}.json` | JSON (reinforcement log) |
