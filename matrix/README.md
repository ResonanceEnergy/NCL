# NARTIX Matrix Monitor

Real-time health and status dashboard for the NARTIX ecosystem.

## Purpose

The Matrix Monitor aggregates health data from all pillars and services into a single view that NATRIX can check from iPhone or Mac.

## Services Monitored

| Service | Port | Health Endpoint | Check Interval |
|---------|------|----------------|---------------|
| Relay | 8787 | /health (HTTPS) | 30s |
| NCL Brain | 8800 | /health | 30s |
| Pump Watcher | — | Process alive check | 60s |
| AAC WAR Room | 8080 | /health | 30s |
| NCC Server | 8765 | /health | 30s |
| Paperclip | 3100 | /api/health | 60s |
| BRS Server | 8000 | /health | 60s |

## Health Check Script

```bash
python3 ~/Projects/nartix-shared/bin/nartix_health.py
```

## Matrix Display Format

Each service reports in a standardized format:

```json
{
  "status": "healthy | degraded | unhealthy | offline",
  "service": "service-name",
  "pnl": 0.0,
  "roi": 0.0,
  "key_metric": 0.0,
  "key_metric_label": "metric_name",
  "uptime_seconds": 3600,
  "last_check": "2026-04-04T12:00:00Z"
}
```

## Integration

- Health data feeds into Paperclip activity log
- CRITICAL status triggers Telegram alert
- Degraded status logged for trend analysis
- Historical health data stored in `matrix/history/` (daily snapshots)
