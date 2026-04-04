# Processed Intelligence Signals

Normalized, scored signals extracted from raw intelligence alerts.

## File Format

Signals are stored as daily JSONL files: `signals-{YYYY-MM-DD}.jsonl`

Each line:
```json
{
  "signal_id": "sig-20260404-001",
  "source_alert_id": "alert-20260404-143022-x",
  "category": "geopolitical",
  "subcategory": "trade_policy",
  "sentiment": 0.72,
  "importance_score": 85,
  "convergence_tags": ["tariff", "china", "semiconductor"],
  "related_signals": ["sig-20260403-018"],
  "timestamp": "2026-04-04T14:30:22Z"
}
```

## Convergence Detection

When 3+ signals share convergence tags within a 48-hour window, Awarebot-FPC triggers a convergence alert and creates a research request in `research-pipeline/queue/`.

## Retention

- Last 30 days: active (queried by pattern detection)
- 30-90 days: cold storage (compressed)
- 90+ days: archived to long-term memory if importance_score >= 70
