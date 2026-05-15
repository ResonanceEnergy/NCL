# Stage 01: Source Ingest

Fetch feeds from X, YouTube, Reddit APIs with deduplication.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| X API | api.x.com | /2/tweets/search/recent | Real-time social signals |
| YouTube API | youtube.googleapis.com | search, trending, comments | Video platform intelligence |
| Reddit API | oauth.reddit.com | subreddits, hot, new | Community discussion signals |

## Process

1. Query X API with watched keywords/accounts
2. Query YouTube trending + search results
3. Query Reddit subreddit feeds (tech, finance, geopolitics)
4. Deduplicate across sources (URL + text hash)
5. Store raw feed with metadata (timestamp, source, engagement)

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Raw Feed | `/dev/NCL/intelligence/raw/{source}_{timestamp}.jsonl` | JSONL |
| Ingest Log | `/dev/NCL/intelligence/ingest.log` | TSV (counts, API latencies) |
