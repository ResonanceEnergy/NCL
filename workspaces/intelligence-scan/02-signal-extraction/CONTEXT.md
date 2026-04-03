# Stage 02: Signal Extraction

Identify actionable signals (trends, anomalies, breaking events) from raw feeds.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 01 | `/Projects/NCL/intelligence/raw/{source}_{timestamp}.jsonl` | All feed items | Signal detection input |
| Watch List | `/Projects/NCL/intelligence/watch_list.yaml` | Keywords, entities, domains | Signal filter config |

## Process

1. Parse feed items (text, metadata, engagement metrics)
2. Match against watch list (keyword, entity, domain)
3. Detect trend indicators (velocity, retweet growth, comment volume)
4. Flag anomalies (unusual engagement, sentiment shift)
5. Extract event candidates (breaking news, releases, announcements)

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Signal Log | `/Projects/NCL/intelligence/signals.log` | JSONL (signal + metadata) |
| Event List | `/Projects/NCL/intelligence/events_{timestamp}.json` | JSON (breaking items) |
