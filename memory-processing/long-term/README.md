# Long-Term Memory

Institutional knowledge that has been validated, consolidated, and indexed for permanent storage.

## Structure

Memories are stored as JSON files organized by domain:

```
long-term/
  geopolitical/
    mem-{id}.json
  market/
    mem-{id}.json
  technical/
    mem-{id}.json
  research/
    mem-{id}.json
  operational/
    mem-{id}.json
```

## Memory Unit Schema

```json
{
  "memory_id": "mem-20260404-geopolitical-001",
  "domain": "geopolitical",
  "title": "US-China semiconductor trade dynamics",
  "content": "Detailed knowledge...",
  "importance": 85.0,
  "confidence": 0.92,
  "source_chain": ["research-20260301-chips", "alert-20260315-export-controls"],
  "tags": ["china", "semiconductor", "trade"],
  "created_at": "2026-03-01T00:00:00Z",
  "last_accessed": "2026-04-04T12:00:00Z",
  "access_count": 14,
  "decay_rate": 0.001,
  "consolidated_from": []
}
```

## Decay Model

Memories decay based on `decay_rate` and time since `last_accessed`. Memories below importance threshold (20.0) after decay are moved to `../decay/` for review. Frequently accessed memories have their decay rate reduced.
