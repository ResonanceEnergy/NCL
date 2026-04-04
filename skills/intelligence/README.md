# Intelligence Skill

Claude skill for running and reviewing Awarebot-FPC intelligence scans.

## Triggers
- `scan` — Run an on-demand intelligence scan across all sources
- `scan {source}` — Scan a specific source (x, youtube, reddit, polymarket)
- `alerts` — Show recent unacknowledged alerts
- `signals {date}` — Show processed signals for a given date
- `convergence` — Check for active convergence patterns

## Behavior

### Scan
1. Dispatches scan request to Awarebot-FPC agent
2. Awarebot queries configured sources (see `intelligence-scan/sources.md`)
3. Raw results are filtered, scored, and stored as alerts
4. Alerts above threshold trigger signal extraction
5. Returns summary of new alerts and any convergence detections

### Convergence Detection
1. Queries last 48 hours of signals
2. Groups by convergence tags
3. Tags with 3+ signals trigger a convergence alert
4. Convergence alerts auto-create research requests for deep investigation

## Integration

- Reads from: `intelligence-scan/signals/`, `intelligence-scan/alerts/`
- Writes to: `intelligence-scan/alerts/` (new alerts), `intelligence-scan/signals/` (processed)
- Triggers: `research-pipeline/queue/` (on convergence detection)
- Runtime: `runtime/awarebot/` (scanner implementations)
