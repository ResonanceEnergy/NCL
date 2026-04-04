# Memory Skill

Claude skill for interacting with NCL's institutional memory system.

## Triggers
- `recall {query}` — Search long-term memory for relevant knowledge
- `remember {fact}` — Store a new memory unit
- `forget {id}` — Mark a memory for decay review
- `memory stats` — Show memory system health metrics

## Behavior

### Recall
1. Parses query into semantic search terms
2. Searches long-term memory by tags, content similarity, and domain
3. Returns top-k results ranked by relevance * importance
4. Logs access (refreshes decay timer on accessed memories)

### Remember
1. Extracts domain, tags, and importance from the provided fact
2. Checks for contradictions with existing memories
3. If contradictions found, flags for council review
4. Otherwise stores as new memory unit in `memory-processing/working/` for consolidation

## Integration

- Reads from: `memory-processing/long-term/`, `memory-processing/working/`
- Writes to: `memory-processing/working/` (new memories)
- Runtime: `runtime/memory/store.py` (MemoryStore class)
