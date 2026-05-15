# NCL Anomaly Log — Unexpected Pattern Registry

**Updated by**: Awarebot-FPC Scanner + Manual NCL entries
**Purpose**: Track anomalies that don't fit normal signal categories
**Authority**: NCL-only write; downstream pillars informed via mandates

---

## Anomaly Schema

```yaml
anomaly_id: ANO-YYYYMMDD-NNN
detected_at: ISO-8601
source: scanner | manual | feedback | convergence
category: data | behavioral | systemic | external
severity: critical | high | medium | low
description: <what was detected>
expected_behavior: <what should have happened>
actual_behavior: <what actually happened>
hypothesis: <best guess at root cause>
resolution: pending | investigating | resolved | dismissed
resolution_notes: <if resolved/dismissed>
related_signals: [SIG-xxx, SIG-yyy]
related_mandates: [MANDATE-xxx]
```

---

## Active Anomalies

### ANO-20260404-001
```yaml
anomaly_id: ANO-20260404-001
detected_at: 2026-04-04T08:00:00Z
source: manual
category: systemic
severity: high
description: "NCL Brain stuck offline — Errno 48 port conflict + pump watcher 403 auth mismatch"
expected_behavior: "Brain binds :8800, watcher forwards pumps with matching token"
actual_behavior: "Stale process held port; token loaded before .env parsed"
hypothesis: "Race condition in STRIKE_TOKEN init + unclean shutdown leaving socket in TIME_WAIT"
resolution: resolved
resolution_notes: "Fixed token loading order (config before env), added graceful SIGTERM handler, boot script now kills port explicitly"
related_signals: []
related_mandates: [MANDATE-2026-008]
```

### ANO-20260404-002
```yaml
anomaly_id: ANO-20260404-002
detected_at: 2026-04-04T09:00:00Z
source: manual
category: systemic
severity: medium
description: "14 pump files stuck in mandate-generation/input/ — zero processed"
expected_behavior: "Pump watcher forwards to brain within 5s of file landing"
actual_behavior: "All POSTs rejected 403, files accumulated over 24h"
hypothesis: "Consequence of ANO-20260404-001 (brain offline + token mismatch)"
resolution: resolved
resolution_notes: "Root cause fixed in ANO-001. Pumps will process on next brain restart."
related_signals: []
related_mandates: [MANDATE-2026-008]
```

---

## Anomaly Categories

| Category | Description | Typical Source |
|----------|-------------|----------------|
| Data | Unexpected data patterns, schema violations, corrupt files | Scanner, feedback |
| Behavioral | Services acting outside expected parameters | Monitoring, logs |
| Systemic | Infrastructure failures, cascade effects | Boot scripts, health checks |
| External | External service changes, API deprecations, market shocks | Scanner, manual |

---

## Escalation Rules

- **Critical**: Auto-spawn council session, notify NATRIX immediately
- **High**: Flag in next mandate review cycle, include in feedback synthesis
- **Medium**: Log and monitor, include in weekly review
- **Low**: Log only, review monthly

---

## Archive

Resolved anomalies older than 30 days are moved to `/NCL/shared/intelligence/archive/anomalies/` with quarterly rollups for pattern analysis.
## 2026-05-15 17:55:51Z — 2 anomalies
- **[market_data/test_anom/bullish]** (93%) SPY whale call sweep $50M
- **[news/test_anom/bearish]** (91%) Major macro event: rate cut

