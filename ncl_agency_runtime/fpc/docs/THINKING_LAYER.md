# Thinking Layer Integration — ICM + OpenClaw + Ralphy

## Overview

FPC v0.5.0 introduces the **Thinking Layer** — a three-system integration that transforms the prediction pipeline from a flat loop into a structured, self-improving, multi-channel system.

| System | Role | Source |
|--------|------|--------|
| **ICM** (Interpretable Context Methodology) | Folder-structure-as-agent-architecture. 5 numbered stages with markdown contracts, audits, and handoffs. | Jake Van Clief — `RinDig/Interpreted-Context-Methdology` |
| **OpenClaw** | Runtime gateway for plugin hooks, cron scheduling, webhook triggers, and multi-channel delivery (Discord, Telegram, Slack, file, API). | `openclaw/openclaw` |
| **Ralphy** | Self-evolution engine. Analyzes prediction accuracy, identifies weaknesses, generates improvement tasks, and recalibrates council weights. | `michaelshimeles/ralphy` |

## Architecture

```
┌─────────────────────────────────────────────────┐
│              ThinkingLayer                      │
│  (src/thinking.py — unified orchestrator)       │
├─────────┬───────────────┬───────────────────────┤
│         │               │                       │
│  ICMPipeline      OpenClawGateway     RalphyEvolution
│  (icm_pipeline.py)  (openclaw_gateway.py) (ralphy_evolution.py)
│         │               │                       │
│  ┌──────┴──────┐   ┌────┴─────┐   ┌────────────┤
│  │ workspace/  │   │ Hooks    │   │ Analyze    │
│  │ stages/     │   │ Cron     │   │ Identify   │
│  │ 01..05/     │   │ Webhooks │   │ Plan       │
│  │ CONTEXT.md  │   │ Channels │   │ Recalibrate│
│  └─────────────┘   └──────────┘   └────────────┘
└─────────────────────────────────────────────────┘
```

## ICM Pipeline Stages

Each stage has a `CONTEXT.md` contract with Inputs/Process/Outputs tables and an Audit checklist.

| Stage | Purpose | Key Artifacts |
|-------|---------|---------------|
| **01-data-ingestion** | Gather signals from 60+ ingesters | `signals.json`, `manifest.json` |
| **02-forecasting** | Run forecast models (StatsForecast, Chronos, Prophet, etc.) | `forecasts.json`, `model_summary.json` |
| **03-council-deliberation** | Each council member analyzes through their specialist lens | `assessments.json`, `explainability.json` |
| **04-consensus** | Weighted vote with calibration and disagreement detection | `prediction.json`, `disagreement.json` |
| **05-delivery** | Format and deliver via configured channels | `report.json`, `delivery.json` |

## CLI Commands

```bash
# Classic council (unchanged)
python -m src.main council "Bitcoin price trajectory" --horizon short

# ICM thinking pipeline (new)
python -m src.main think "Bitcoin price trajectory" --horizon medium

# Ralphy self-evolution analysis (new)
python -m src.main evolve
```

## OpenClaw Hooks

Three plugin lifecycle hooks are registered by default:

| Hook | When | Action |
|------|------|--------|
| `before_prompt_build` | Before council deliberation | Inject domain-specific data sources |
| `after_tool_call` | After each tool result | Audit tool results for errors |
| `agent_end` | After final prediction | Capture prediction for delivery |

## Ralphy Evolution Cycle

```
Analyze → Identify → Plan → Execute → Verify
  ↑                                      │
  └──────────────────────────────────────┘
```

The evolution engine:
1. Reviews prediction accuracy from `PredictionTracker`
2. Checks data source coverage (60 ingesters across 12 domains)
3. Evaluates strategy diversity (5 forecasting models)
4. Generates prioritized `EvolutionTask` items
5. Suggests weight recalibration when accuracy drops below 40%

## Configuration

`config/thinking_config.json` controls all three subsystems:

```json
{
    "workspace_root": "workspace",
    "gateway_url": "http://127.0.0.1:18789",
    "channels": { "file": { "output_dir": "reports" } },
    "evolution": { "accuracy_threshold_low": 0.40, "auto_recalibrate": true }
}
```

## File Manifest

| File | Lines | Purpose |
|------|-------|---------|
| `src/icm_pipeline.py` | ~380 | 5-stage pipeline engine with contract parsing |
| `src/openclaw_gateway.py` | ~300 | WebSocket bridge, hooks, cron, webhooks, channels |
| `src/ralphy_evolution.py` | ~340 | Self-assessment, task generation, weight recalibration |
| `src/thinking.py` | ~230 | Unified orchestrator tying all three together |
| `config/thinking_config.json` | ~25 | Configuration for all subsystems |
| `workspace/CONTEXT.md` | ~40 | ICM Layer 1 routing table |
| `workspace/stages/*/CONTEXT.md` | ~5 files | Stage contracts with Inputs/Process/Outputs/Audit |
| `workspace/stages/*/references/*.md` | ~12 files | Domain reference material per stage |
| `tests/test_thinking_integration.py` | ~280 | 36 tests covering all three subsystems |
