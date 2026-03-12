# Daily Collect

Gather data from all NCL sources for the daily intelligence cycle.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Event log | `../../../data/event_log/` | Last 24h entries | Recent events |
| Derived data | `../../../data/derived/` | Last 24h entries | Recent insights |
| YouTube digest | `../../../data/youtube_digest.ndjson` | Last 24h entries | Content intake |
| Mission reports | `../../mission-ops/stages/04-report/output/` | Last 24h | Mission outcomes |

## Process

1. Scan data/event_log/ for events from the last 24 hours
2. Scan data/derived/ for insights generated in the last 24 hours
3. Read recent YouTube digest entries
4. Collect mission reports from mission-ops if any exist
5. Compile a collection manifest listing all gathered data points
6. Write the collection to output/

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Daily collection | output/[date]-collection.json | JSON manifest |
