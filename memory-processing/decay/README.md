# Memory Decay Queue

Memories that have fallen below the importance threshold and are candidates for archival or deletion.

## Process

1. Memory consolidation runs on schedule (default: every hour)
2. Each long-term memory's effective importance is recalculated: `importance * e^(-decay_rate * days_since_accessed)`
3. Memories with effective importance < 20.0 are moved here
4. Weekly review:
   - If a decayed memory is referenced by an active mandate or recent signal, it's restored to long-term with refreshed importance
   - If unreferenced for 30+ days in decay, it's permanently archived (compressed, not deleted)

## File Format

Same as long-term memory units, with additional field:
```json
{
  "decayed_at": "2026-04-04T00:00:00Z",
  "original_importance": 45.0,
  "effective_importance": 18.3,
  "decay_reason": "no_access_60_days | low_confidence | superseded"
}
```
