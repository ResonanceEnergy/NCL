# NUREALCORTEXLINK (NCL) v3.0

Cognitive augmentation platform. Second brain system that captures iPhone data streams,
synthesizes insights, and maintains collective intelligence across human and AI agents.

## Folder Map

```
NCL/
├── CLAUDE.md                              (you are here)
├── CONTEXT.md                             (task routing)
├── _config/                               (shared conventions and templates)
│   ├── CONVENTIONS.md                     (source of truth for all ICM patterns)
│   └── templates/                         (blank starting points)
├── workspaces/
│   ├── mission-ops/                       (mission processing pipeline)
│   ├── data-pipeline/                     (iPhone data capture and synthesis)
│   ├── agent-dev/                         (agent creation and hardening)
│   └── daily-ops/                         (daily intelligence operations)
├── ncl_agency_runtime/                    (agent runtime engine)
│   ├── agents/                            (agent implementations)
│   ├── fpc/                               (Future Predictor Council — merged)
│   │   ├── agents/                        (20-agent framework, orchestrator)
│   │   ├── council/                       (model council, ensemble, scoring)
│   │   ├── eval/                          (backtesting, evaluation)
│   │   ├── causal/                        (DoWhy/EconML causal inference)
│   │   ├── xai/                           (SHAP explainability)
│   │   ├── serve/                         (FastAPI serve layer)
│   │   └── data/                          (predictions, caches)
│   ├── runtime/                           (daemon, dispatcher, executor)
│   ├── missions/                          (mission queue)
│   └── config/                            (runtime configuration)
├── data/                                  (event log, quarantine, derived)
├── schemas/                               (JSON Schema catalog, 43+ event types)
├── docs/                                  (doctrine, setup guides, contracts)
│   └── fpc/                               (FPC docs, bootcamp, backlog)
├── evaluation/                            (golden tasks, scoring harness)
├── tools/                                 (health check, export, import, validation)
├── tests/                                 (pytest suite, incl. test_fpc_*.py)
├── fractal_future/                        (research tracks, entropy maps)
├── future_predictor_council/              (DEPRECATED — shimmed to ncl_agency_runtime/fpc)
├── ncl_onedrop_setup/                     (product dev, roadmap tracking)
├── ncl_gbx_one_drop/                      (build system)
├── ios/                                   (iOS companion app)
└── shortcuts_pack/                        (iOS Shortcuts)
```

## Routing

| You want to...                          | Go to                                      |
|-----------------------------------------|--------------------------------------------|
| Process a mission end-to-end            | `workspaces/mission-ops/CONTEXT.md`        |
| Ingest and process iPhone data          | `workspaces/data-pipeline/CONTEXT.md`      |
| Create or harden an agent               | `workspaces/agent-dev/CONTEXT.md`          |
| Run daily intelligence operations       | `workspaces/daily-ops/CONTEXT.md`          |
| Read the full ICM conventions           | `_config/CONVENTIONS.md`                   |
| Validate schemas                        | `schemas/ncl.iphone.v1/index.json`         |
| Run golden task evaluations             | `evaluation/golden_tasks/`                 |
| Check system health                     | `tools/system_health_check.py`             |
| Read NCC doctrine                       | `NCC_Master_Doctrine_v2.0.md`              |
| Work on FPC forecasting                 | `ncl_agency_runtime/fpc/`                  |
| Read FPC docs                           | `docs/fpc/`                                |

## What to Load

| Task                     | Load These                                    | Do NOT Load                         |
|--------------------------|-----------------------------------------------|-------------------------------------|
| Mission processing       | mission-ops workspace, ncl_agency_runtime     | data-pipeline, fractal_future       |
| Data ingestion           | data-pipeline workspace, schemas, tools       | agent-dev                           |
| Agent development        | agent-dev workspace, tests, evaluation        | daily-ops, ios, shortcuts_pack      |
| Daily brief              | daily-ops workspace, ncl_agency_runtime       | agent-dev, ncl_gbx_one_drop         |
| Schema work              | schemas/, docs/ncl_iphone_data_contract_v1.md | workspaces, fractal_future          |
| Test/eval                | tests/, evaluation/, evaluation_harness.py    | workspaces, ios                     |

## Triggers

| Keyword  | Action                                                    |
|----------|-----------------------------------------------------------|
| `setup`  | Run onboarding in whatever workspace you are in           |
| `status` | Show pipeline completion for the current workspace        |

## How It Works

Each workspace is self-contained with its own CONTEXT.md. Navigate into a workspace
folder and that workspace's CONTEXT.md takes over. You do not need to read this
root file once you are inside a workspace.
