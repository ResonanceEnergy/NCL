# BRS Revenue Reports

Feedback reports from the BRS (Business Revenue System) pillar documenting economic signals.

## Report Schema

Files named `brs-report-{YYYY-MM-DD}-{report_id}.json`:

```json
{
  "report_id": "brs-report-20260404-001",
  "report_type": "economic_signal",
  "source_pillar": "BRS",
  "timestamp": "2026-04-04T18:00:00Z",
  "period": "2026-04-01/2026-04-04",
  "revenue_summary": {
    "gross_revenue_usd": 0.0,
    "net_revenue_usd": 0.0,
    "revenue_sources": [],
    "pipeline_value_usd": 0.0
  },
  "product_signals": [
    {
      "product": "DIGITAL-LABOUR",
      "metric": "page_views",
      "value": 0,
      "trend": "flat",
      "note": "Pre-launch — site live but no inbound leads yet"
    }
  ],
  "conversion_insights": [],
  "market_fit_indicators": [],
  "cost_of_revenue": {
    "api_costs_usd": 0.0,
    "hosting_costs_usd": 0.0,
    "marketing_costs_usd": 0.0
  }
}
```

## Flow

BRS produces daily/weekly reports. NCL synthesizes these with NCC execution truth and AAC capital performance to maintain a complete picture of the studio's economic state.
