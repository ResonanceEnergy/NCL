# Stage 01: Source Scan

Fetch from arXiv, web, GitHub repos, academic papers based on research briefs.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Briefs | `/dev/NCL/research/briefs/{topic}.md` | Topic + keywords | Research direction |
| Standing List | `/dev/NCL/research/standing_topics.yaml` | Active research areas | Continuous scan scope |

## Process

1. Parse research brief - extract keywords and source types
2. Query arXiv, Google Scholar, GitHub, web sources
3. Fetch full text or abstracts (dedup across sources)
4. Build source catalog with metadata (date, author, DOI, URL)
5. Store raw sources for stage 02

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Source Catalog | `/dev/NCL/research/sources/{topic}_{date}.json` | JSON (metadata + links) |
| Raw Sources | `/dev/NCL/research/sources/raw/{uuid}.txt` | Plain text (extracted text) |
