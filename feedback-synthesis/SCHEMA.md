# Feedback Report Schema

All pillar feedback reports MUST conform to this schema. Reports are dropped as
JSON files into `feedback-synthesis/{ncc,brs,aac}-reports/` by their respective
pillars. The synthesis scanner (`runtime/feedback/scanner.py`) consumes them on
a 5-minute interval and produces interpreted notes in `synthesis/`.

## Report file naming

```
{pillar}-{YYYYMMDD}-{HHMMSS}-{slug}.json
```

Example: `ncc-20260514-203015-strike-point-build.json`

## Report schema (v1)

```json
{
  "schema_version": "1.0",
  "report_id": "ncc-20260514-203015",
  "pillar": "NCC",                          // NCC | BRS | AAC
  "report_type": "execution",               // execution | revenue | capital | health
  "mandate_id": "MANDATE-20260514-001",    // optional; null if pillar-initiated
  "timestamp": "2026-05-14T20:30:15Z",
  "summary": "One-sentence interpreted result. Never raw data.",
  "outcome": "success",                     // success | partial | failed | blocked
  "metrics": {                              // pillar-specific, structured
    "duration_seconds": 1234,
    "cost_cents": 50,
    "...": "..."
  },
  "blockers": [                             // empty if outcome=success
    "Paperclip unreachable on :3100"
  ],
  "next_action_request": null               // optional: what NCL should mandate next
}
```

## Authority Chain rule

> Feedback ↑ (interpreted only, never raw data)

Pillars MUST pre-process raw logs/metrics into interpreted summaries before
writing reports. The synthesis cortex will NOT do log parsing.

## Synthesis output

The scanner produces `synthesis/synth-{YYYYMMDD-HHMMSS}.json` containing:
- Recently consumed reports (by pillar)
- Aggregate outcome counts
- Open blockers across pillars
- Suggested mandate adjustments (free-text, for council review)
