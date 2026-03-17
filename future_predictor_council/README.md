# Future Predictor Council — DEPRECATED

> **This directory is deprecated.** All FPC code has been merged into
> `ncl_agency_runtime/fpc/`. The backward-compatibility shim in
> `src/__init__.py` will continue to work but emits a `DeprecationWarning`.
>
> - **Source code:** `ncl_agency_runtime/fpc/`
> - **Config:** `ncl_agency_runtime/config/fpc/`
> - **Tests:** `tests/test_fpc_*.py`
> - **Docs:** `docs/fpc/`
> - **Data:** `ncl_agency_runtime/fpc/data/`
>
> Do not add new code here. This directory will be removed in a future release.

---

## Original README (archived)

Local-first, agentic forecasting stack with model council, rolling backtest, XAI panels, causal what-ifs, and optional foundation-model burst.

## Architecture

```
[Ingestion Layer]
  Metrics TS  → Parquet / DuckDB
  Text/News   → Embeddings (regime covariates)
  Events      → Event log (Hawkes/alerts)

[Feature Layer]
  Calendar/holidays, lagged/rolling, regime tags, known future covariates

[Model Council]
  A) Foundation TS: TimesFM, Chronos-2
  B) Neural LTSF:   PatchTST / TFT / Informer
  C) Statistical:   AutoARIMA/ETS/Theta (StatsForecast) + Silverkite
  D) Event:         Neural Hawkes (when-predictions)

[Adjudication]
  Cross-validated model selection per series cohort
  Ensembles (weighted or meta-learner stacking)

[Explainability & Causality]
  TimeSHAP/SHAP/IG per forecast
  DoWhy/EconML for intervention what-ifs and uplift

[Validation & Backtesting]
  Rolling-origin CV; MASE/sMAPE/CRPS dashboards

[Serving]
  Local-first API (CPU) with cloud burst for foundation models

[Ops & Governance]
  Drift monitors, consent/PII guardrails, action-gated change mgmt
```

## Quickstart

```bash
cd future_predictor_council
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .

# Run baseline backtest (local-first, fast CPU)
python -m src.cli --data data/raw/example.csv --freq D --h 14 --foundation off

# Burst with foundation models (requires GPU/high-RAM or cloud)
pip install -e ".[foundation]"
python -m src.cli --data data/raw/example.csv --freq D --h 14 --foundation on
```

## Data Format

Long panel with columns:
- `unique_id` (str) — series identifier
- `ds` (datetime) — timestamp
- `y` (float) — target value

## Compute Profile (Ryzen 5, 16 GB RAM)

| Tier | What Runs | Notes |
|------|-----------|-------|
| GREEN | StatsForecast, Silverkite, DoWhy, EconML, SHAP | Fast on CPU |
| YELLOW | PatchTST/TFT (NeuralForecast) | Slow on CPU; reduce input_size/layers |
| RED | TimesFM (needs ≥32 GB RAM), Chronos-2 (needs GPU) | Use cloud burst |

## 10-Agent Launch Squadron

| # | Agent | Mission |
|---|-------|---------|
| 1 | Mission Control (Supervisor) | Route work, enforce approvals, merge PRs |
| 2 | Data Steward | Data contracts, schema validation, features |
| 3 | Baselines Engineer | StatsForecast + Silverkite baselines |
| 4 | Neural Engineer | PatchTST/TFT CPU-lite + GPU presets |
| 5 | Foundation Ops | Chronos-2 on A10G; TimesFM on ≥64 GB RAM |
| 6 | XAI Engineer | SHAP + TimeSHAP dossiers |
| 7 | Causal Scientist | DoWhy + EconML, refuters, policy |
| 8 | MLOps Engineer | CI/CD, drift, containers, scheduled backtests |
| 9 | Security & Privacy | PII redaction, provenance, audit gates |
| 10 | DX & Docs | Guides, screenshots, API docs, bootcamp |

## Project Structure

```
future_predictor_council/
├── src/
│   ├── council/        # Model strategies + ensemble
│   ├── eval/           # Metrics + rolling backtest
│   ├── xai/            # SHAP + TimeSHAP panels
│   ├── causal/         # DoWhy + EconML panels
│   ├── agents/         # 10-agent orchestrator (LangGraph + AutoGen)
│   ├── serve/          # FastAPI local server
│   └── cli.py          # One-liner pipeline runner
├── config/             # Steering knobs (5% human input)
├── data/raw/           # Drop CSV/Parquet here
├── doctrine/           # Palantir emulation + predictor doctrine
├── backlog/            # Epics, stories, issues
├── bootcamp/           # 5-day Arena Bootcamp kit
├── ops/                # Apollo-lite release policy + airgap
├── docs/               # USAGE, XAI, CAUSAL, FOUNDATION guides
└── tests/
```

## 90-Day Execution Plan

| Sprint | Weeks | Focus |
|--------|-------|-------|
| S1 | 1–2 | Baselines + data contracts + CI |
| S2 | 3–4 | Neural + ensemble (CPU-lite) |
| S3 | 5–6 | XAI dossier (SHAP + TimeSHAP) |
| S4 | 7–8 | Causal what-ifs (DoWhy + EconML) |
| S5 | 9–10 | Foundation burst (Chronos-2 + TimesFM) |
| S6 | 11–12 | MLOps, containers, drift, docs bundle |

## Steering Knobs (5% Human Input)

See `config/steering.json`:
- Gate metric: MASE (primary), sMAPE (secondary)
- Causal interventions: Promo, Price
- Cloud: AWS (A10G for Chronos-2, ≥64 GB RAM for TimesFM)
- Weekly budget cap: $50
