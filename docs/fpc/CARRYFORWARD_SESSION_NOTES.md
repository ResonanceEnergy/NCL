# CARRYFORWARD SESSION NOTES — Future Predictor Council

**Date:** 2025-07-12
**Project:** `future_predictor_council/` within `c:\dev\NCL`
**Branch:** `feat/golden-tasks` (PR #18 → main)

---

## 1. What Was Built

A comprehensive multimodal forecasting platform with:

- **Model Council**: 4 strategies (StatsForecast, PatchTST, TimesFM 2.5, Chronos-2) + weighted ensemble
- **Rolling Backtest**: Sliding-window cross-validation with MASE/sMAPE metrics
- **XAI Panels**: SHAP (global/local feature importance) + TimeSHAP (sequential attribution)
- **Causal Panels**: DoWhy (ATE via identify→estimate→refute) + EconML (CATE via LinearDML/CausalForestDML)
- **10-Agent Launch Squadron**: Mission Control, Data Steward, Baselines Engineer, Neural Engineer, Foundation Ops, XAI Engineer, Causal Scientist, MLOps Engineer, Security Officer, DX Docs
- **LangGraph Orchestrator**: Supervisor pattern with task queue and approval gates
- **Cloud Burst**: Cost-capped AWS bursting for foundation models ($50/week, $1.20/hr GPU max)
- **FastAPI Server**: /health, /forecast, /explain, /whatif endpoints
- **CLI**: argparse entry point for backtest runner
- **Palantir Emulation**: 200 insights across 20 clusters, doctrine, 42-story backlog
- **Arena Bootcamp**: 5-day curriculum with demo scenario
- **Apollo-lite Ops**: Release policy (alpha/beta/stable), air-gap bundles, SBOM/Trivy gates
- **CI/CD**: micro_backtest.yml + security.yml GitHub Actions workflows
- **VS Code config**: settings.json, tasks.json, launch.json, 13 smoke tests

## 2. Key Decisions

| Decision | Rationale |
|----------|-----------|
| Council-of-models over single model | Diversity reduces catastrophic failure risk |
| MASE as primary metric | Scale-independent, <1 beats naive baseline |
| Local-first architecture | Ryzen 5 7530U / 16 GB DDR5, no discrete GPU |
| Cloud burst opt-in | Foundation models (TimesFM ≥32 GB, Chronos-2 needs A10G GPU) |
| 5% human steering | Only 5 knobs: metric gate, interventions, cloud, series priorities, budget |
| Apollo-lite deployment | Canary channels (10%→30%→100%) with automatic rollback |
| Explain-before-act principle | Every forecast ships with XAI dossier |

## 3. Compute Profile

| Tier | Models | CPU Time | RAM | Where |
|------|--------|----------|-----|-------|
| GREEN | StatsForecast (AutoARIMA, ETS, Theta) | <2 min/1K series | <4 GB | Local |
| YELLOW | NeuralForecast (PatchTST, TFT) | ~15 min train | ~8 GB | Local |
| RED | TimesFM 2.5 | ~10 min/1K series | ≥32 GB | Cloud (r6i.2xlarge $0.504/hr) |
| RED | Chronos-2 | ~5 min/1K series | ≥16 GB + GPU | Cloud (g5.xlarge $1.006/hr) |

**Weekly budget cap:** $50 | **Daily GPU max:** 60 minutes | **Foundation default:** OFF

## 4. File Inventory

### Source Code (15 files)
- `src/__init__.py` — Package root
- `src/cli.py` — CLI entry point
- `src/council/__init__.py` — Council package
- `src/council/base.py` — ModelStrategy ABC + ForecastResult
- `src/council/strategy_statsforecast.py` — CPU baselines
- `src/council/strategy_patchtst.py` — Neural LTSF
- `src/council/strategy_timesfm.py` — TimesFM 2.5 foundation
- `src/council/strategy_chronos.py` — Chronos-2 foundation
- `src/council/ensemble.py` — Weighted ensemble
- `src/eval/__init__.py` — MASE + sMAPE metrics
- `src/eval/rolling_backtest.py` — Sliding-window CV
- `src/xai/__init__.py` — TimeSHAP panel
- `src/xai/shap_panel.py` — SHAP panel
- `src/causal/__init__.py` — DoWhy panel
- `src/causal/econml_panel.py` — EconML CATE panel

### Agent Team (3 files)
- `src/agents/__init__.py` — 10 agent role definitions
- `src/agents/orchestrator.py` — LangGraph supervisor
- `src/agents/burst.py` — Cost-capped cloud burst

### API (1 file)
- `src/serve/__init__.py` — FastAPI endpoints

### Config + Data (2 files)
- `config/steering.json` — 5% human steering knobs
- `data/raw/example.csv` — Synthetic 2-series daily panel

### Doctrine (2 files)
- `doctrine/FUTURE_PREDICTOR_DOCTRINE.md` — Core principles P1–P8
- `doctrine/DOCTRINE_PALANTIR_EMULATION.md` — 200 insights, 20 clusters

### Backlog (2 files)
- `backlog/BACKLOG_PALANTIR_EMULATION.md` — 6 epics, 42 stories
- `backlog/issues.yaml` — Machine-readable issue seeds

### Bootcamp (6 files)
- `bootcamp/Day1_scope.md` through `bootcamp/Day5_train.md`
- `bootcamp/demo_scenario/scenario_config.yaml`

### Ops (3 files)
- `ops/ReleasePolicy.yaml` — Apollo-lite channels
- `ops/airgap/README.md` + `ops/airgap/make_airgap_bundle.sh`

### Docs (5 files)
- `docs/USAGE.md`, `docs/XAI_GUIDE.md`, `docs/CAUSAL_GUIDE.md`
- `docs/FOUNDATION_REMOTE.md`, `docs/COMPUTE_PROFILE.md`

### DevOps (7 files)
- `README.md`, `pyproject.toml`, `Makefile`
- `.vscode/settings.json`, `.vscode/tasks.json`, `.vscode/launch.json`
- `tests/test_smoke.py` (13 tests)
- `.github/workflows/micro_backtest.yml`, `.github/workflows/security.yml`
- `scripts/ISSUES_SEED.md`, `scripts/create_issues.sh`

## 5. Palantir Emulation Strategy

200 insights distilled from Palantir's public engineering into 20 clusters:
AIP, Ontology, OSDK, Scenarios, Platform, Apollo, Gotham, AIP Security, Bootcamps,
Observability, Model Mgmt, TITAN, NHS, Financials, Product Security, Data/Logic/Action,
Interop, Edge/DDIL, Adoption, Narrative.

Each cluster maps to concrete council features via the emulation matrix in
`doctrine/DOCTRINE_PALANTIR_EMULATION.md`.

## 6. Next Steps (Priority Order)

1. **Install base deps**: `pip install -e ".[dev]"` from `future_predictor_council/`
2. **Run smoke tests**: `python -m pytest tests/test_smoke.py -v`
3. **First backtest**: `python -m src.cli --data data/raw/example.csv --freq D --h 14`
4. **Wire real data**: Replace `example.csv` with actual time series
5. **XAI dossier**: Run SHAP + TimeSHAP on baseline results
6. **Causal what-if**: Set up DoWhy DAG for domain-specific interventions
7. **Foundation burst**: Enable `--foundation chronos2` with AWS credentials
8. **GitHub Issues**: Run `scripts/create_issues.sh` to populate backlog
9. **Bootcamp Day 1**: Follow `bootcamp/Day1_scope.md` with real use case
10. **CI green**: Ensure `micro_backtest.yml` passes on PR

## 7. Dependencies Not Yet Installed

```
# Base (required)
pandas, numpy, pyyaml

# Neural (optional)
neuralforecast, pytorch-lightning

# XAI (optional)
shap, timeshap

# Causal (optional)
dowhy, econml

# Foundation (optional, cloud burst)
timesfm, chronos

# Agents (optional)
langgraph, autogen

# API (optional)
fastapi, uvicorn

# Dev
pytest, ruff, mypy
```

## 8. Integration Points with NCL

- **NCL Memory System**: Council results can be stored via `ncl_memory.py`
- **NCL Agency Runtime**: Orchestrator aligns with `ncl_agency_runtime/` patterns
- **NCL Config**: Steering knobs follow `ncl_config.json` conventions
- **Golden Tasks**: Forecast accuracy tasks can become golden task evaluations
- **Fractal Future**: Entropy principles (P0–P8) inform council diversity strategy

---

*Session notes generated for continuity. All files written to `c:\dev\NCL\future_predictor_council\`.*
