# Feedback Synthesis

Integrated interpretation of feedback from all downstream pillars (NCC, BRS, AAC).

## Purpose

This is where raw pillar reports are cross-referenced, validated, and distilled into actionable intelligence for NCL's mandate generation process. Raw data never reaches NCL directly — only synthesized interpretations.

## Synthesis Output Schema

Files named `synthesis-{YYYY-MM-DD}.json`:

```json
{
  "synthesis_id": "synthesis-20260404",
  "timestamp": "2026-04-04T20:00:00Z",
  "period": "2026-04-01/2026-04-04",
  "input_reports": {
    "ncc": ["ncc-report-20260404-001"],
    "brs": ["brs-report-20260404-001"],
    "aac": ["aac-report-20260404-001"]
  },
  "cross_pillar_findings": [
    {
      "finding": "All services stable, no execution friction",
      "confidence": 0.95,
      "source_pillars": ["NCC", "AAC"],
      "impact": "positive"
    }
  ],
  "mandate_recommendations": [
    {
      "type": "no_change | adjust | new_mandate | deprecate",
      "mandate_id": "MANDATE-2026-008",
      "recommendation": "No adjustment needed — pipeline operating within parameters",
      "urgency": "LOW"
    }
  ],
  "ecosystem_health_score": 0.85,
  "next_synthesis_due": "2026-04-07T20:00:00Z"
}
```

## Schedule

- Daily: Lightweight health synthesis (automated)
- Weekly: Full cross-pillar synthesis with mandate review
- On-demand: Triggered by CRITICAL alerts or doctrine state changes
