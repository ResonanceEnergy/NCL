# Path to Operational — Future Predictor Council

> Status: **OPERATIONAL.** All 20 agents wired to real implementations.
> All quality gates green: 710 tests passing, ruff clean, mypy clean.

---

## System Status — Operational

| Layer | Module | Status |
|-------|--------|--------|
| **Infrastructure** | `orchestrator.py` | ✅ Full 9-phase state machine (OBSERVE → RECOVER) |
| **Infrastructure** | `router.py` | ✅ In-process event routing, dedup, privacy gate, DLQ |
| **Infrastructure** | `policy.py` | ✅ Budget caps, burst validation, release channels, rollback triggers, security gates |
| **Infrastructure** | `events.py` | ✅ Typed events with tracing, privacy, cost tags |
| **Infrastructure** | `live.py` | ✅ `boot()` wires everything; `dispatch_*()` API works end-to-end |
| **Model Council** | `strategy_statsforecast.py` | ✅ AutoARIMA + AutoETS + AutoTheta |
| **Model Council** | `strategy_patchtst.py` | ✅ PatchTST via neuralforecast (graceful fallback) |
| **Model Council** | `strategy_timesfm.py` | ✅ TimesFM 2.5 (graceful fallback) |
| **Model Council** | `strategy_chronos.py` | ✅ Chronos-2 (graceful fallback) |
| **Model Council** | `ensemble.py` | ✅ Weighted average of any strategy set |
| **Evaluation** | `eval/__init__.py` | ✅ MASE + sMAPE metrics |
| **Evaluation** | `rolling_backtest.py` | ✅ Sliding-window cross-validation |
| **CLI / API** | `cli.py` | ✅ `--data --freq --h --foundation` → full pipeline |
| **API** | `serve/__init__.py` | ✅ `/forecast` + `/health` endpoints |
| **Config** | `steering.json` | ✅ $50/wk budget, GPU caps, quantiles, seasonality |
| **Config** | `ReleasePolicy.yaml` | ✅ 3-channel promotion, rollback triggers, security gates |
| **Tests** | `test_agent_framework.py` | ✅ 65 tests — framework + integration |
| **Tests** | `test_smoke.py` | ✅ 12 tests — council, eval, agents, burst, orchestrator |

## 20-Agent Roster — All Wired

### Launch Squadron (10 Agents)

| # | Callsign | Codename | Real Implementation |
|---|----------|----------|-------------------|
| 1 | SCRIBE | ds | CSV loading, schema validation, null detection, IQR anomaly detection |
| 2 | TEMPO | be | StatsForecastStrategy (AutoARIMA+ETS+Theta), real MASE/sMAPE on hold-out |
| 3 | ORACLE | ne | PatchTSTStrategy with graceful ImportError fallback |
| 4 | BEHEMOTH | fo | Real `can_burst()` + `estimate_cost()` from burst.py |
| 5 | LANTERN | xe | Correlation-based feature importance (lag-1 autocorr, rolling trend, volatility) |
| 6 | RAVEN | cs | DoWhy causal estimation with median-split proxy fallback |
| 7 | FORGE | mo | Real project health checks (steering.json, requirements, data pipeline) |
| 8 | PHALANX | so | Real SBOM from importlib.metadata, budget anomaly flagging |
| 9 | ECHO | dx | Real markdown briefs from event context |
| 10 | ATLAS | mc | Real agent count + steering config introspection |

### Expansion Pack (10 Agents)

| # | Callsign | Codename | Real Implementation |
|---|----------|----------|-------------------|
| 11 | MINDGATE | ir | Multi-pattern keyword scoring with confidence + agent routing |
| 12 | PHOENIX | ss | Bootstrap Monte Carlo simulation from real data distribution |
| 13 | NAVIGATOR | rp | Data-size-aware resource allocation planning |
| 14 | SANCTUM | es | Skewness-based bias detection + zero-inflation check |
| 15 | WATCHTOWER | em | Real agent health checks + data drift detection |
| 16 | MUSE | ux | Real system status summary |
| 17 | COUNCILOR | an | Model comparison + consensus detection from MASE spreads |
| 18 | NIGHTFALL | hr | Circuit breakers from budget/latency/security thresholds |
| 19 | SPECTRE | rt | Adversarial edge-case scanning |
| 20 | BRIDGE | si | Real filesystem probe for connected NCL subsystems |

## Quality Gates

| Gate | Status |
|------|--------|
| **Tests** | ✅ 710/710 passing (77 framework + 633 NCL core) |
| **Ruff** | ✅ All checks passed (0 errors) |
| **Mypy** | ✅ Success: 90 source files, 0 errors |
| **StrEnum migration** | ✅ All str+Enum classes upgraded to StrEnum |
| **Import modernization** | ✅ typing.Dict → dict, typing.Sequence → collections.abc |

---

## Next Steps (Enhancement Opportunities)

### Scale Up
- **State persistence**: Add SQLite backend for `OrchestratorState` and loop history
- **Message broker**: Replace in-process `EventRouter` with Redis Streams for durability
- **LangGraph migration**: Optional port when multi-agent routing gets complex

### Production Hardening
- **Cloud burst**: Wire `boto3` calls in `burst.py` → `start_burst()` for real EC2 launches
- **LLM NLU**: Upgrade MINDGATE from keyword matching to LLM-based intent classification
- **Artifact versioning**: Add MLflow or filesystem model versioning in FORGE
- **TLS + auth**: Harden the serve API with authentication and request limits

**After Phase 1:** `boot()` → `dispatch_intent("forecast X")` → real MASE,
real predictions, real data quality scores. The system produces value.

---

## Metric Gates (from steering.json + ReleasePolicy.yaml)

| Gate | Threshold | Enforced By |
|------|-----------|-------------|
| MASE < 1.0 | Required for beta promotion | PolicyEngine |
| Error rate < 1% | Required for stable promotion | PolicyEngine |
| p95 latency < 5s | Required for stable promotion | PolicyEngine |
| Budget ≤ $50/week | Hard cap | PolicyEngine + ATLAS |
| GPU ≤ $1.20/hr | Hard cap | BurstConfig |
| GPU ≤ 60 min/day | Hard cap | BurstConfig |
| SBOM present | Required for any channel | PolicyEngine |
| Vuln scan clean | Required for any channel | PolicyEngine |
