# Feedback Synthesis Senders

HTTP-based feedback submission pipeline for NARTIX NCL Brain. Pillar-specific senders (NCC, BRS, AAC) and a synthesis orchestrator.

## Overview

- **ncc_sender.py** — Submit NCC execution reports to NCL Brain
- **brs_sender.py** — Submit BRS economic reports to NCL Brain
- **aac_sender.py** — Submit AAC capital reports to NCL Brain
- **synthesizer.py** — Orchestrate multi-pillar synthesis via council

All scripts:
- Read `STRIKE_AUTH_TOKEN` from `NCL/.env` (or environment)
- Validate YAML report schemas before submission
- Use httpx for async HTTP (no blocking I/O)
- Support CLI interfaces with `argparse`

## Configuration

Set in `NCL/.env`:

```bash
NCL_BRAIN_URL=http://localhost:8800
STRIKE_AUTH_TOKEN=your-auth-token-here
```

Or pass as environment variables:

```bash
export NCL_BRAIN_URL=http://localhost:8800
export STRIKE_AUTH_TOKEN=your-token
python ncc_sender.py --list
```

## Usage

### NCC Sender

Submit execution reports from NCC:

```bash
# Send specific report
python ncc_sender.py ncc-reports/execution_2026_04_06.yaml

# Send all pending reports
python ncc_sender.py --all

# List pending reports
python ncc_sender.py --list

# Custom brain URL
python ncc_sender.py --brain-url http://localhost:9999 --all
```

Report schema (required fields):

```yaml
title: "Execution Report - April 6, 2026"
timestamp: 1712437200           # Unix timestamp
execution_status: success       # success|partial|failed
outcomes:
  - "Task A completed"
  - "Task B deferred"
category: general               # general|error|opportunity|risk
```

### BRS Sender

Submit revenue reports from BRS:

```bash
python brs_sender.py --list
python brs_sender.py brs-reports/revenue_2026_q1.yaml --all
```

Report schema (required fields):

```yaml
title: "Q1 Revenue Report"
timestamp: 1712437200
revenue_total: 125000           # Numeric value
metrics:
  conversion_rate: 0.045
  avg_deal_size: 5000
category: general
```

### AAC Sender

Submit capital reports from AAC:

```bash
python aac_sender.py --list
python aac_sender.py aac-reports/performance_2026_04.yaml
```

Report schema (required fields):

```yaml
title: "April Capital Performance"
timestamp: 1712437200
capital_deployed: 500000        # Numeric value
performance_metrics:
  roi: 0.12
  drawdown: 0.05
category: general
```

### Synthesizer

Orchestrate multi-pillar feedback synthesis:

```bash
# Run full synthesis (calls council, saves output)
python synthesizer.py

# Debug output
python synthesizer.py --debug

# Dry run (show what would be synthesized, no API calls)
python synthesizer.py --dry-run
```

The synthesizer:
1. Collects recent reports (last 7 days) from all pillars
2. Calls NCL council to synthesize patterns + risks + opportunities
3. Saves synthesis JSON to `synthesis/synthesis_YYYYMMDD_HHMMSS.json`
4. POSTs synthesis to NCL Brain for mandate integration

## Integration with Pillar Pipelines

### NCC Integration

In NCC execution pipeline:

```bash
# After execution pass:
python /Users/natrix/dev/NCL/feedback-synthesis/senders/ncc_sender.py \
  --all --brain-url http://localhost:8800
```

### BRS Integration

In BRS revenue reporting:

```bash
# Daily revenue sync:
python /Users/natrix/dev/NCL/feedback-synthesis/senders/brs_sender.py \
  --all
```

### AAC Integration

In AAC capital cycle:

```bash
# Weekly performance report:
python /Users/natrix/dev/NCL/feedback-synthesis/senders/aac_sender.py \
  --all
```

## Error Handling

All scripts gracefully degrade:

- **Brain offline** → Log error, exit with code 1
- **Invalid report** → Log validation error, skip report
- **Auth failure** → Log 401/403 error, fail submission
- **Network timeout** → Log timeout, suggest manual retry

Check logs for details:

```bash
python ncc_sender.py --all 2>&1 | grep ERROR
```

## API Contracts

### Submit Report Endpoint

```
POST /feedback

Headers:
  Authorization: Bearer {STRIKE_AUTH_TOKEN}
  Content-Type: application/json

Body:
{
  "pillar": "NCC" | "BRS" | "AAC",
  "report_content": "YAML string (parsed on server)",
  "category": "general" | "error" | "opportunity" | "risk"
}

Response:
{
  "report_id": "uuid",
  "status": "received",
  "processing": "queued" | "analyzing" | "synthesizing",
  "created_at": 1712437200.5
}
```

### Spawn Council Endpoint

```
POST /council/spawn

Headers:
  Authorization: Bearer {STRIKE_AUTH_TOKEN}
  Content-Type: application/json

Body:
{
  "topic": "feedback-synthesis",
  "question": "Synthesize NCC/BRS/AAC feedback...",
  "council_type": "cloud"
}

Response:
{
  "session_id": "uuid",
  "status": "spawned",
  "council_members": ["Claude", "Grok", "Gemini", "Perplexity", "GPT"],
  "question": "...",
  "deliberation_started": 1712437200.5
}
```

### Submit Synthesis Endpoint

```
POST /feedback/synthesis

Headers:
  Authorization: Bearer {STRIKE_AUTH_TOKEN}
  Content-Type: application/json

Body:
{
  "synthesis": {
    "timestamp": "2026-04-06T22:35:00Z",
    "council_session_id": "uuid",
    "pillar_summary": {
      "ncc_reports": 3,
      "brs_reports": 2,
      "aac_reports": 1
    },
    "council_response": {...}
  }
}

Response:
{
  "status": "accepted",
  "synthesis_id": "uuid"
}
```

## Monitoring & Ops

### Health Check

```bash
curl -H "Authorization: Bearer $STRIKE_AUTH_TOKEN" \
  http://localhost:8800/health
```

### View Report Queue

```bash
# See all pending reports
python ncc_sender.py --list
python brs_sender.py --list
python aac_sender.py --list
```

### View Synthesis History

```bash
ls -lah synthesis/
tail -f synthesis/synthesis_*.json | jq .
```

## Testing

Mock test reports:

```bash
mkdir -p /tmp/test-reports/{ncc,brs,aac}-reports

cat > /tmp/test-reports/ncc-reports/test.yaml <<'EOF'
title: Test NCC Report
timestamp: $(date +%s)
execution_status: success
outcomes:
  - Test outcome 1
  - Test outcome 2
EOF

python ncc_sender.py /tmp/test-reports/ncc-reports/test.yaml --brain-url http://localhost:8800
```

## Architecture Notes

- **Async HTTP**: All senders use httpx AsyncClient (non-blocking I/O)
- **Schema validation**: Pillar-specific required fields validated before submission
- **Error resilience**: Individual report failures don't block subsequent reports
- **Local sync**: Reports staged locally first, submitted to brain via HTTP
- **Synthesis orchestration**: Synthesizer calls council, captures response, saves JSON locally + posts to brain

This implements the "interpreted feedback only" doctrine: raw reports are validated, synthesized via council, then posted as integrated intelligence (never raw data to NCL).
