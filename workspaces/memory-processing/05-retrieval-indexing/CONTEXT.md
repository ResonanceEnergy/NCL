# Stage 05: Retrieval Indexing

Build searchable indices for fast recall by context, recency, confidence, domain.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 04 | `/Projects/NCL/memory/index_decayed_{date}.json` | Decayed consolidated index | Indexing source |

## Process

1. Load decayed consolidated index
2. Build keyword index (full-text search)
3. Build recency index (sort by observation_date desc)
4. Build confidence index (sort by confidence desc)
5. Build domain index (group by topic/domain tags)
6. Build temporal index (time-windowed queries: "last 7 days", "last quarter")

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Index Bundle | `/Projects/NCL/memory/indices/` | JSON files (keyword, recency, confidence, domain, temporal) |
| Index Manifest | `/Projects/NCL/memory/index_manifest_{date}.json` | JSON (index metadata + build timestamp) |
