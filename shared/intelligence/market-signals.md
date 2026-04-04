# NCL Market Signals — Live Intelligence Feed

**Updated by**: Awarebot-FPC Scanner
**Frequency**: Every 5 minutes (X), 10 minutes (YouTube/Reddit)
**Authority**: NCL reads only; NCC/BRS/AAC consume via mandates

---

## Signal Schema

Each signal follows this format:

```yaml
signal_id: SIG-YYYYMMDD-NNN
source: x | youtube | reddit | news | manual
timestamp: ISO-8601
category: geopolitical | market | tech | cultural | anomaly
confidence: 0.0-1.0
urgency: critical | high | normal | low
summary: <one-line description>
raw_data_ref: <path to raw scan output>
pillar_relevance:
  - NCL: <why this matters to strategy>
  - AAC: <trading/investment implications>
  - BRS: <revenue/product implications>
  - NCC: <execution implications>
decay_hours: 24  # signal relevance half-life
```

---

## Active Signals

> Populated by Awarebot-FPC scanner at runtime.
> Signals older than their decay window are moved to archive.

### Template Entry

```yaml
signal_id: SIG-20260404-001
source: manual
timestamp: 2026-04-04T00:00:00Z
category: tech
confidence: 0.8
urgency: normal
summary: "NARTIX ecosystem context audit complete — 85% coverage"
raw_data_ref: null
pillar_relevance:
  - NCL: Context network gaps identified and being filled
  - NCC: No execution impact
  - BRS: No revenue impact
  - AAC: No capital impact
decay_hours: 168
```

---

## Signal Categories

| Category | Sources | Typical Decay | AAC Relevance |
|----------|---------|---------------|---------------|
| Geopolitical | X, News | 48-168h | High (war room scenarios) |
| Market | X, Reddit | 4-24h | Critical (trading signals) |
| Tech | YouTube, Reddit, X | 72-336h | Medium (tooling/infra) |
| Cultural | X, YouTube | 24-72h | Low (brand/content) |
| Anomaly | All | 1-12h | Variable (convergence detection) |

---

## Convergence Detection

When 3+ signals from different sources align on the same theme within a 24h window, the scanner flags a **convergence event**. These get elevated to `urgency: critical` and trigger an automatic council spawn via NCL mandate-generation pipeline.

Convergence thresholds:
- **Strong**: 5+ signals, 3+ sources, confidence avg > 0.7
- **Moderate**: 3-4 signals, 2+ sources, confidence avg > 0.5
- **Weak**: 2 signals, 2 sources — logged but no auto-action

---

## Archive

Decayed signals are moved to `/NCL/shared/intelligence/archive/` with monthly rollups.
