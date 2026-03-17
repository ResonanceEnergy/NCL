# Future Predictor Council — Doctrine

> The governing principles, architecture decisions, and strategic alignment
> for the multimodal forecasting platform.

---

## Mission

Build a **council-of-models forecasting platform** that:
- Produces probabilistic forecasts with uncertainty quantification
- Explains predictions through XAI (SHAP, TimeSHAP)
- Enables causal what-if analysis (DoWhy, EconML)
- Runs 95% autonomously with 5% human steering
- Operates local-first with cloud burst for heavy compute

## Core Principles

### P1 — Council over Monoculture
No single model owns the forecast. A weighted ensemble of diverse strategies
(statistical, neural, foundation) produces more robust predictions than any
individual model. Disagreement between council members is signal, not noise.

### P2 — Explain Before Act
Every forecast must be accompanied by feature attributions (SHAP/TimeSHAP)
and causal estimates (DoWhy/EconML). A prediction without explanation is a
liability, not an asset.

### P3 — Measure Everything, Trust Nothing
MASE is the primary gate. sMAPE is secondary. Rolling backtest is mandatory
before any model enters the council. If it can't beat seasonal naive (MASE < 1),
it doesn't ship.

### P4 — Human Steering, Not Human Driving
Five knobs: metric gate, causal interventions, cloud toggle, series priorities,
weekly budget cap. Everything else is autonomous. The human sets the destination;
the agents drive.

### P5 — Local First, Cloud Burst
CPU baselines (StatsForecast, Silverkite) run locally. Neural models (PatchTST, TFT)
train locally but slowly. Foundation models (TimesFM, Chronos-2) burst to cloud
with cost caps ($50/week, $1.20/hr GPU max).

### P6 — Offline Resilient
Unreliable internet is assumed. All core functionality works offline. Cloud burst
is optional enhancement, not dependency. One-drop packaging for data transfer.

### P7 — Security by Construction
SBOM generation (Syft), vulnerability scanning (Trivy), scoped credentials,
audit trails. Security is not a phase — it's a property of the system.

### P8 — Composability over Completeness
Every component (strategy, eval, XAI, causal) is independently usable.
The ensemble composes them; the CLI orchestrates them; the API serves them.
No monolithic coupling.

## Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Primary metric | MASE | Scale-independent, interpretable (< 1 = beats naive) |
| Ensemble method | Weighted average | Simple, auditable, extensible |
| Agent framework | LangGraph + AutoGen | Supervisor pattern + design-time collab |
| API framework | FastAPI | Async, typed, auto-docs |
| XAI | SHAP + TimeSHAP | Global + sequential attribution |
| Causal | DoWhy + EconML | DAG + CATE estimation |
| Package management | pyproject.toml + extras | Optional heavy deps via extras |
| Release policy | Apollo-lite channels | Alpha → Beta → Stable with soak |

## Compute Profile

| Tier | Models | Hardware | Location |
|---|---|---|---|
| GREEN | StatsForecast, Silverkite, DoWhy | Ryzen 5 7530U, 16GB | Local |
| YELLOW | PatchTST, TFT | Same (slow training) | Local |
| RED | TimesFM (≥32GB RAM), Chronos-2 (A10G GPU) | Cloud instances | AWS burst |

## Strategic Alignment

This project operates within the **NCL (Neural Command Layer)** ecosystem:
- **NCC Governance**: Council decisions are auditable and reversible
- **NCL Memory**: Forecast results and model performance feed the memory system
- **AAC Integration**: Trading signal generation from forecast outputs
- **BRS**: Agent team follows Super OpenClaw patterns

## Palantir Emulation

See [DOCTRINE_PALANTIR_EMULATION.md](DOCTRINE_PALANTIR_EMULATION.md) for the
full 200-insight analysis and emulation matrix.

---

*Doctrine version: 1.0*
