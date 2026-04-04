# Memory Architecture

## Three-Tier Memory Model

### Working Memory
- **Purpose**: Active session context
- **Lifetime**: Session-scoped (hours)
- **Storage**: `memory-processing/working/`
- **Capacity**: ~50 concurrent entries
- **Access**: Direct read/write during active tasks

### Long-Term Memory
- **Purpose**: Institutional knowledge
- **Lifetime**: Permanent (with decay)
- **Storage**: `memory-processing/long-term/` organized by domain
- **Capacity**: Unlimited (file-based)
- **Access**: Indexed search by tags, domain, content similarity

### Decay Queue
- **Purpose**: Staging area for fading memories
- **Lifetime**: 30-day review window
- **Storage**: `memory-processing/decay/`
- **Recovery**: Memories can be restored if referenced by active context

## Consolidation Process

Runs hourly via scheduled task:

1. **Episodic intake**: New experiences from councils, research, and intelligence are captured
2. **Semantic extraction**: Key facts, relationships, and insights are extracted
3. **Deduplication**: Check against existing memories for overlaps
4. **Consolidation**: Merge related memories, update confidence scores
5. **Decay check**: Calculate effective importance, move faded memories to decay queue
6. **Index update**: Refresh tag index and domain catalogs

## Memory Unit Lifecycle

```
New fact → Working Memory → Consolidation → Long-Term Memory
                                                    ↓ (low access + time)
                                              Decay Queue
                                                    ↓ (30 days unreferenced)
                                              Permanent Archive (compressed)
```

## Runtime Implementation

- `runtime/memory/store.py` — MemoryStore class (file-based CRUD)
- `runtime/memory/models.py` — MemoryUnit Pydantic model
- Consolidation scheduled via Paperclip or launchd
