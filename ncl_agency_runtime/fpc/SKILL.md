---
name: future-predictor-council
version: 0.6.0
author: ResonanceEnergy
license: MIT
description: Multi-agent council for structured predictions with 5-stage ICM pipeline, OpenClaw delivery, and self-evolution.
category: forecasting
tags:
  - prediction
  - forecasting
  - council
  - multi-agent
  - time-series
  - icm
  - openclaw
runtime: python
python_version: ">=3.9"
entry_point: src/main.py
api_endpoint: /api/v1
api_port: 8000
---

# Future Predictor Council — SKILL

Multi-agent prediction council with a 5-stage ICM pipeline, multi-channel delivery, and self-evolving accuracy.

## Capabilities

| Capability | Description |
|-----------|-------------|
| **Council Deliberation** | 4+ specialist council members analyze from different lenses (contrarian, bayesian, historian, technician) |
| **ICM Pipeline** | 5-stage structured pipeline: ingestion → forecasting → deliberation → consensus → delivery |
| **Forecasting Ensemble** | StatsForecast, Prophet, Chronos, NeuralForecast, TimesFM — weighted consensus |
| **Multi-Channel Delivery** | File, API, Discord webhook, Telegram bot, Slack webhook, OpenClaw gateway |
| **Self-Evolution** | Ralphy engine tracks accuracy, identifies weaknesses, recalibrates weights |
| **Alerting** | Anomaly detection, risk flagging, stale data warnings, evolution backlogs |
| **Helix News** | AI news anchor: script generation → TTS audio → SadTalker video |
| **Signal Ingestion** | 60+ data sources across crypto, financial markets, macro, climate, health, technology |

## Tools

### predict
Run a council prediction on a topic.

**Parameters:**
- `topic` (string, required) — What to predict
- `horizon` (string, optional) — "short" | "medium" | "long" | "strategic". Default: "medium"
- `channels` (array[string], optional) — Delivery channels: ["file", "discord", "telegram", "slack"]

**Returns:** Prediction object with direction, confidence, reasoning, and dissenting views.

### think
Run the full ICM 5-stage pipeline for a deep prediction.

**Parameters:**
- `topic` (string, required) — What to analyze
- `horizon` (string, optional) — Prediction timeframe. Default: "medium"
- `run_evolution` (boolean, optional) — Run Ralphy self-assessment after. Default: true

**Returns:** Full ThinkingResult with pipeline stages, prediction, delivery status, evolution report.

### backtest
Run a rolling backtest on time-series data.

**Returns:** Backtest metrics (MASE, sMAPE) across multiple windows.

### scrape
Collect signals from configured data sources.

**Parameters:**
- `tier` (string, optional) — "tier_1_daily" | "tier_2_weekly" | "tier_3_monthly" | "tier_4_quarterly"

**Returns:** Signal counts by tier.

### evolve
Run Ralphy self-evolution analysis.

**Returns:** Accuracy stats, strengths, weaknesses, improvement tasks, weight recommendations.

### alerts
Get active system alerts.

**Parameters:**
- `level` (string, optional) — Filter: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"

**Returns:** List of active alerts sorted by severity.

## Configuration

```json
{
    "council_name": "Future Predictor Council",
    "gateway_url": "http://127.0.0.1:18789",
    "channels": {
        "file": {"output_dir": "reports"},
        "discord": {"enabled": false, "webhook_url": "", "format": "summary"},
        "telegram": {"enabled": false, "bot_token": "", "chat_id": "", "format": "summary"},
        "slack": {"enabled": false, "webhook_url": "", "format": "summary"}
    }
}
```

## API Endpoints

When running in serve mode (`fpc serve`):

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/predict` | Run council prediction |
| GET | `/api/v1/predictions` | List all predictions |
| GET | `/api/v1/predictions/{id}` | Get specific prediction |
| POST | `/api/v1/think` | Run ICM pipeline |
| POST | `/api/v1/ingest` | Trigger signal ingestion |
| GET | `/api/v1/status` | Flywheel status |
| GET | `/api/v1/council/members` | List council members |
| POST | `/api/v1/backtest` | Run rolling backtest |
| GET | `/api/v1/alerts` | Get active alerts |
| GET | `/health` | Health check (no auth) |

All endpoints (except `/health`) require `Authorization: Bearer <token>` header.

## Installation

```bash
pip install -r requirements.txt
```

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `FPC_API_TOKEN` | Yes (for API) | Bearer token for API auth |
| `OPENCLAW_API_KEY` | No | OpenClaw gateway API key |

## Integration with OpenClaw

FPC registers three plugin lifecycle hooks:
1. `before_prompt_build` — Injects domain context (crypto, stock, macro, climate sources)
2. `after_tool_call` — Audits tool results before forwarding
3. `agent_end` — Captures final prediction for delivery pipeline

Connect via: `ws://127.0.0.1:18789` (WebSocket) or `http://127.0.0.1:18789/api/messages` (REST)
