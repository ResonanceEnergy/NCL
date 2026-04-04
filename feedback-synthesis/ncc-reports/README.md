# NCC Execution Reports

Feedback reports from the NCC (Command Center) pillar documenting execution truth.

## Report Schema

Files named `ncc-report-{YYYY-MM-DD}-{report_id}.json`:

```json
{
  "report_id": "ncc-report-20260404-001",
  "report_type": "execution_truth",
  "source_pillar": "NCC",
  "timestamp": "2026-04-04T18:00:00Z",
  "mandate_id": "MANDATE-2026-008",
  "execution_summary": {
    "tasks_dispatched": 12,
    "tasks_completed": 10,
    "tasks_failed": 1,
    "tasks_blocked": 1,
    "completion_rate": 0.833
  },
  "friction_points": [
    {
      "description": "Relay TLS cert regeneration took 8s on cold start",
      "severity": "LOW",
      "suggested_fix": "Cache certs with 24h TTL"
    }
  ],
  "services_health": {
    "relay": "healthy",
    "brain": "healthy",
    "pump_watcher": "healthy",
    "aac_war_room": "degraded"
  },
  "deployment_log": [],
  "next_cycle_recommendations": []
}
```

## Flow

NCC produces these reports after each execution cycle. They enter NCL feedback synthesis pipeline where they're validated, cross-referenced with BRS/AAC reports, and distilled into mandate adjustments if warranted.
