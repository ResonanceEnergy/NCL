# AAC Capital Reports

Feedback reports from the AAC (Asset Allocation Controller) pillar documenting capital performance.

## Report Schema

Files named `aac-report-{YYYY-MM-DD}-{report_id}.json`:

```json
{
  "report_id": "aac-report-20260404-001",
  "report_type": "capital_performance",
  "source_pillar": "AAC",
  "timestamp": "2026-04-04T18:00:00Z",
  "period": "2026-04-01/2026-04-04",
  "portfolio_summary": {
    "current_aum_usd": 10000000.0,
    "peak_aum_usd": 10000000.0,
    "drawdown_pct": 0.0,
    "doctrine_state": "NORMAL"
  },
  "pnl": {
    "realized_pnl_usd": 0.0,
    "unrealized_pnl_usd": 0.0,
    "total_pnl_usd": 0.0,
    "roi_pct": 0.0
  },
  "war_room": {
    "active_scenarios": 0,
    "positions_open": 0,
    "positions_closed": 0,
    "win_rate": 0.0
  },
  "strategy_attribution": [],
  "market_intelligence": [],
  "risk_events": []
}
```

## Doctrine State Reporting

AAC reports its current doctrine state (NORMAL / CAUTION / SAFE_MODE / HALT) in every report. State transitions are logged with full context so NCL can evaluate whether doctrine parameters need adjustment.
