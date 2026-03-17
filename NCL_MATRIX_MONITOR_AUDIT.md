# NCL MATRIX MONITOR — Complete System Audit & NCC Integration Readiness Report

**Date:** 2025-07-10  
**Scope:** All monitoring, health, metrics, SLO, and dashboard code in `c:\dev\NCL`  
**Purpose:** Prepare NCL Matrix Monitor for integration under NCC Matrix Monitor  

---

## 1. EXECUTIVE SUMMARY

**Current State:** NCL has **4,871 lines of monitoring code across 13 Python files** — but it is **fragmented across 6 independent subsystems** with no common interface, no shared data model, and no unified dashboard. The "Matrix Monitor" concept exists in the roadmap (Steps 79, 91–100) but has **zero dedicated implementation** — the `matrix_dashboard.md` is a 7-line stub.

**Key Finding:** The building blocks are solid and working. Integration into NCC Matrix Monitor requires a **thin unification layer**, not a rewrite.

| Metric | Value |
|--------|-------|
| Total monitoring LOC | 4,871 |
| Python files | 13 |
| Test files covering monitoring | 4 (2,429 LOC) |
| Health endpoints | 2 (`/health` on ports 8787, 8123) |
| Gap scanners | 9 (in autonomous daemon) |
| Self-check checks | 8 (in self_check_protocol) |
| System health checks | 10 (in system_health_check) |
| FPC health checks | 4 (in fpc_integration) |
| Agent health checks | 4 (in HealthMonitor) |
| Pillar registry checks | 4 (heartbeat, triad, status, summary) |
| **Critical untested components** | **4** (system_health_check, self_check_protocol, autonomous_daemon, setup_wizard) |

---

## 2. MONITORING LANDSCAPE — WHAT EXISTS

### Layer 1: System-Level Health (`tools/`)

| File | LOC | Checks | Has Tests |
|------|-----|--------|-----------|
| `tools/system_health_check.py` | 280 | 10 checks (deps, dirs, schemas, golden tasks, APIs, shortcuts, tests, runtime, onedrop, ICM workspaces) | **NO** |
| `tools/setup_wizard.py` | 222 | 6 steps (dirs, Python, deps, config, imports, tests) | **NO** |
| `tools/validate_events.py` | 96 | Schema validation against `ncl.iphone.v1` | Indirect |

**Architecture:** Standalone CLI scripts, no shared interface. `system_health_check.py` generates markdown reports. No persistence of historical results.

### Layer 2: Self-Check Protocol (`ncl_agency_runtime/runtime/`)

| File | LOC | Checks | Has Tests |
|------|-----|--------|-----------|
| `self_check_protocol.py` | 400 | 8 deep checks (code integrity via AST, imports, config, memory vitals, disk, ports, doctrine, evolution score) | **NO** |

**Architecture:** Standalone engine with 0.0–1.0 scoring model. Outputs JSON to `logs/selfcheck_latest.json`. Tracks evolution via `selfcheck_history.ndjson`. Health labels: EXCELLENT/GOOD/FAIR/DEGRADED/CRITICAL.

### Layer 3: Autonomous Daemon Gap Analyzer (`ncl_agency_runtime/runtime/`)

| File | LOC | Scanners | Has Tests |
|------|-----|----------|-----------|
| `autonomous_daemon.py` | 1,100 | 9 scanners (test health, lint health, roadmap gaps, config completeness, file structure, documentation, dependency health, log anomalies, FPC health) | **NO** |

**Architecture:** Full PDCA daemon with enums (TaskPriority, TaskStatus, DaemonPhase, EscalationLevel), self-generated work units (`AutonomousTask`), `GapAnalyzer` (9 scanners), `TaskGenerator` (converts gaps → prioritized tasks), `CycleReport`. File logging to `logs/autonomous_daemon.log`. Most sophisticated monitoring layer.

### Layer 4: NCC Governance Layer (`ncl_agency_runtime/runtime/`)

| File | LOC | Capabilities | Has Tests |
|------|-----|-------------|-----------|
| `pillar_registry.py` | 309 | Heartbeat, set_status, health_summary, triad_online, triad_status | **YES** (616 LOC) |
| `ncc_orchestrator.py` | 343 | PDCA cycle, cross-pillar routing, health reports, DL dispatch | **YES** (shared) |
| `inter_pillar_bus.py` | ~380 | MessageType.HEARTBEAT, ALERT, STATUS_REPORT, pub/sub, stats | **YES** (shared) |
| `fpc_integration.py` | 406 | scan_fpc_health (4 checks: dir, scrapers, predictions, cache) | Indirect |

**Architecture:** This IS the NCC Matrix Monitor foundation. `PillarRegistry` tracks all 4 pillars (NCL/AAC/SA/DL) + NCC itself. `NCCOrchestrator.run_pdca_cycle()` executes Plan→Do→Check→Act with health gathering. The bus carries HEARTBEAT/ALERT messages. Well-tested.

### Layer 5: Agent-Level Health (`ncl_agency_runtime/agents/`)

| File | LOC | Capabilities | Has Tests |
|------|-----|-------------|-----------|
| `super_openclaw_agent.py` (HealthMonitor class) | ~60 | 4 checks (memory, skills, channels, backpressure) + async heartbeat loop | **YES** (test_super_openclaw_agent.py) |

**Architecture:** Embedded in the agent — publishes `health.heartbeat` events to the EventBus every N seconds. Checks memory_offline, no_skills_loaded, no_channels. Reports uptime, message count.

### Layer 6: HTTP Health Endpoints

| Endpoint | File | Port | Response | Has Tests |
|----------|------|------|----------|-----------|
| `GET /health` | `relay_server.py` | 8787 | `{"status": "healthy", "timestamp": ..., "memory": {...}}` | **YES** (437 LOC) |
| `GET /health` | `backend/api/main.py` | 8123 | `{"status": "ok"}` (stub) | **NO** |

### Layer 7: FPC Agent Roster (Stubs)

| Agent | Role | Implementation |
|-------|------|----------------|
| WATCHTOWER (#15) | Event Monitor — stream processing, anomaly detection, alert routing, health dashboards | **Stub** — returns mock data |
| FORGE (#8) | MLOps Engineer — deployment success rate, MTTR, monitoring dashboards | **Stub** |
| NIGHTFALL (#18) | Emergency Response — circuit breakers | **Stub** |
| SENTINEL (#22) | NCC Doctrine Enforcer — Three Pillars scoring, PDCA audit | **Stub** |

---

## 3. DEPENDENCY MAP

```
NCC Matrix Monitor (proposed)
│
├── ncl_agency_runtime/runtime/
│   ├── ncc_orchestrator.py      ← PDCA governance, cross-pillar routing
│   │   ├── pillar_registry.py   ← heartbeat, health_summary, triad_status
│   │   ├── inter_pillar_bus.py  ← HEARTBEAT/ALERT message transport
│   │   └── digital_labour.py   ← task dispatch for monitoring actions
│   │
│   ├── autonomous_daemon.py     ← 9-scanner gap analyzer + PDCA loop
│   │   └── fpc_integration.py  ← FPC health scanning (4 checks)
│   │
│   └── self_check_protocol.py   ← 8-check deep introspection + scoring
│
├── ncl_agency_runtime/agents/
│   └── super_openclaw_agent.py  ← HealthMonitor (4 checks, async heartbeat)
│
├── ncl_agency_runtime/fpc/agents/
│   ├── __init__.py              ← WATCHTOWER/FORGE/SENTINEL role definitions
│   └── stubs.py                 ← stub implementations
│
├── tools/
│   ├── system_health_check.py   ← 10-check top-level diagnostic
│   ├── setup_wizard.py          ← 6-step onboarding validation
│   └── validate_events.py       ← schema validation
│
├── ncl_onedrop_setup/backend/
│   └── api/main.py              ← /health stub
│
└── ncl_config.json              ← master configuration (ports, paths, flags)
```

---

## 4. TEST COVERAGE ANALYSIS

### Covered (3 core files, ~1,600 combined test LOC)

| Component | Test File | Coverage Notes |
|-----------|-----------|----------------|
| PillarRegistry | `test_ncc_integration.py` (616 LOC) | heartbeat, set_status, health_summary, triad_online, triad_status |
| NCCOrchestrator | `test_ncc_integration.py` | handle_ncc_health_command, bootstrap, PDCA cycle |
| InterPillarBus | `test_ncc_integration.py` | HEARTBEAT/ALERT publish/subscribe |
| RelayServer /health | `test_relay_server.py` (437 LOC) | RateLimiter, AuthManager, config, auth enforcement |
| WATCHTOWER agent | `test_fpc_agent_framework.py` (563 LOC) | test_watchtower_health_monitoring (basic) |
| HealthMonitor | `test_super_openclaw_agent.py` | test_health_monitor_check |

### UNCOVERED — Critical Gap

| Component | LOC | Risk | Impact |
|-----------|-----|------|--------|
| `system_health_check.py` | 280 | **HIGH** — top-level diagnostic, no regression protection | System health regressions go undetected |
| `self_check_protocol.py` | 400 | **HIGH** — evolution scoring, AST parsing, doctrine checks | Self-healing regression |
| `autonomous_daemon.py` | 1,100 | **CRITICAL** — 9 scanners, PDCA loop, task generation | Core autonomous ops untested |
| `setup_wizard.py` | 222 | MEDIUM — onboarding path | New user experience regression |
| `backend/api/main.py` | 24 | LOW — trivial stub | Minimal risk |

**Test Debt:** 2,002 LOC of monitoring code (41%) has zero test coverage.

---

## 5. GAP ANALYSIS — WHAT'S MISSING FOR NCC MATRIX MONITOR

### Gap 1: No Unified Check Interface
Each subsystem defines checks differently:
- `system_health_check.py` → methods returning `bool`
- `self_check_protocol.py` → returns `CheckResult` dataclass (name, passed, score, details, recommendation)
- `autonomous_daemon.py` → returns `list[dict]` from gap scanners
- `pillar_registry.py` → returns `dict` from `health_summary()`
- HealthMonitor → returns ad-hoc `dict`

**Fix Required:** Define a universal `HealthCheck` protocol that all subsystems implement.

### Gap 2: No Centralized Dashboard / Aggregation
Health data is scattered:
- `selfcheck_latest.json` (written by self_check_protocol)
- `selfcheck_history.ndjson` (evolution tracking)
- `autonomous_daemon.log` (file)
- `/health` HTTP responses (ephemeral)
- PillarRegistry in-memory only (no persistence)
- HealthMonitor publishes to EventBus (ephemeral)

**Fix Required:** A single `MatrixMonitorStore` that collects, persists, and serves all health data.

### Gap 3: No SLO Framework
Roadmap Step 79 ("Matrix Monitor wires for SLO alerts") and Step 91 ("SLO tiles") reference SLOs, but:
- No SLO definitions exist
- No error budget tracking
- No alerting mechanism
- No T2N (Time-to-Note), Search P95, Q&A P95 metrics

**Fix Required:** SLO definitions (target, window, budget) + metric collectors + alert thresholds.

### Gap 4: No Alert Routing 
NIGHTFALL agent (emergency response) is a stub. The InterPillarBus has `MessageType.ALERT` but no consumer triggers alerts based on health transitions. `self_check_protocol` labels health as CRITICAL/DEGRADED but no downstream action fires.

**Fix Required:** Alert rules engine: condition → severity → routing (log / bus / escalation).

### Gap 5: WATCHTOWER Agent is a Stub
WATCHTOWER is the designated "Event Monitor" (agent #15) — should handle stream processing, anomaly detection, alert routing, and health dashboards. Currently returns mock data.

**Fix Required:** Wire WATCHTOWER to consume HealthCheck results and drive the Matrix Monitor dashboard.

### Gap 6: No Dashboard Tiles Implementation
`matrix_dashboard.md` lists 4 tile types but zero implementation:
- Progress Tile (from `/progress`)
- Roadmap Tile (render markdown from `/roadmap`)
- SLO Tiles (T2N, Search P95, Q&A P95)
- Adoption Tiles (D7/D30, local-only sessions)

**Fix Required:** Dashboard data API that serves tile data in a standardized format.

---

## 6. NCC INTEGRATION ARCHITECTURE — PROPOSED

### Target Architecture

```
NCC MATRIX MONITOR
═══════════════════════════════════════════════════════════
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │         MatrixMonitorOrchestrator                │   │
│  │  (single entry point, runs all collectors)       │   │
│  └────────────────┬────────────────────────────────┘   │
│                   │                                     │
│    ┌──────────────┼──────────────┐                     │
│    │              │              │                      │
│    ▼              ▼              ▼                      │
│  ┌──────┐   ┌──────────┐   ┌──────────┐               │
│  │System│   │  NCC      │   │  Agent   │               │
│  │Health│   │Governance │   │  Health  │               │
│  │Checks│   │  Checks   │   │  Checks  │               │
│  └──┬───┘   └────┬─────┘   └────┬─────┘               │
│     │            │              │                       │
│     └────────────┼──────────────┘                       │
│                  ▼                                      │
│  ┌─────────────────────────────────────────────────┐   │
│  │         MatrixMonitorStore                       │   │
│  │  (unified persistence: JSON + NDJSON history)    │   │
│  └────────────────┬────────────────────────────────┘   │
│                   │                                     │
│    ┌──────────────┼──────────────┐                     │
│    │              │              │                      │
│    ▼              ▼              ▼                      │
│  ┌──────┐   ┌──────────┐   ┌──────────┐               │
│  │ SLO  │   │  Alert   │   │  Dash    │               │
│  │Engine│   │  Router  │   │  Tiles   │               │
│  └──────┘   └──────────┘   └──────────┘               │
│                                                         │
═══════════════════════════════════════════════════════════
```

### Mapping Existing Code → NCC Architecture

| NCC Component | Existing Code to Wire | New Code Needed |
|---------------|----------------------|-----------------|
| **MatrixMonitorOrchestrator** | `autonomous_daemon.GapAnalyzer.full_scan()` | Thin wrapper that calls all collectors |
| **System Health Checks** | `system_health_check.NCLHealthChecker.run_all_checks()` | Adapt return type to `HealthCheck` protocol |
| **NCC Governance Checks** | `pillar_registry.health_summary()` + `ncc_orchestrator.run_pdca_cycle()` | Already compatible |
| **Agent Health Checks** | `HealthMonitor.check()` + `self_check_protocol.run_all()` | Adapt return type |
| **FPC Health Checks** | `fpc_integration.scan_fpc_health()` | Already returns `list[dict]` |
| **MatrixMonitorStore** | `selfcheck_latest.json` pattern | New: unified store with history |
| **SLO Engine** | Nothing exists | **NEW** — define SLOs, track budgets |
| **Alert Router** | `inter_pillar_bus` ALERT message type exists | **NEW** — rules engine + routing |
| **Dashboard Tiles** | OneDrop `/progress` + `/roadmap` exist | **NEW** — tile data API |

### Integration Touchpoints with NCC Orchestrator

1. **`NCCOrchestrator.run_pdca_cycle()` PLAN phase** → calls `MatrixMonitorOrchestrator.collect_all()` instead of just `registry.health_summary()`
2. **`NCCOrchestrator.run_pdca_cycle()` CHECK phase** → evaluates SLO budget consumption
3. **`InterPillarBus` HEARTBEAT handler** → feeds data into `MatrixMonitorStore`
4. **`PillarRegistry.health_summary()`** → becomes one data source among many (not the only one)
5. **`autonomous_daemon` gap scanners** → feed gap count into SLO metrics

---

## 7. INTEGRATION READINESS SCORECARD

| Criterion | Score | Notes |
|-----------|-------|-------|
| **Monitoring code exists** | 8/10 | 4,871 LOC across 13 files — solid foundation |
| **Health checking works** | 7/10 | 35+ individual checks across 5 subsystems, all functional |
| **Test coverage** | 4/10 | 59% covered, 3 critical components untested |
| **Unified interface** | 2/10 | No common protocol — each subsystem is bespoke |
| **Data persistence** | 3/10 | Only self_check_protocol persists; rest is ephemeral |
| **SLO framework** | 0/10 | Not implemented at all |
| **Alert routing** | 1/10 | Bus message type exists, no rules engine |
| **Dashboard/tiles** | 1/10 | 7-line stub doc, OneDrop has `/progress` and `/roadmap` |
| **NCC governance wiring** | 8/10 | Orchestrator + Registry + Bus fully operational |
| **Agent integration** | 3/10 | WATCHTOWER stub, HealthMonitor works but isolated |
| **Overall Readiness** | **3.7/10** | **Foundation strong, unification layer missing** |

---

## 8. RECOMMENDED INTEGRATION PLAN

### Phase 1: Foundation (Unify) — ~500 LOC new code

1. **Define `HealthCheck` protocol** in `ncl_agency_runtime/runtime/matrix_monitor.py`:
   ```python
   @dataclass
   class HealthCheckResult:
       source: str        # "system" | "ncc" | "agent" | "fpc" | "self_check"
       name: str
       passed: bool
       score: float       # 0.0–1.0
       details: str
       recommendation: str
       timestamp: str
   ```

2. **Create `MatrixMonitorOrchestrator`** that:
   - Calls `NCLHealthChecker.run_all_checks()` → adapts to `HealthCheckResult`
   - Calls `SelfCheckProtocol.run_all()` → already returns compatible format
   - Calls `PillarRegistry.health_summary()` → adapts to `HealthCheckResult`
   - Calls `scan_fpc_health()` → adapts to `HealthCheckResult`
   - Produces unified `MatrixReport` with overall score + per-source breakdown

3. **Create `MatrixMonitorStore`** that:
   - Writes `logs/matrix_latest.json` (current snapshot)
   - Appends to `logs/matrix_history.ndjson` (trend data)
   - Supports `get_latest()`, `get_history(hours=24)`, `get_trend(metric, days=7)`

### Phase 2: SLOs + Alerts — ~400 LOC new code

4. **SLO definitions** in `ncl_config.json` under new `"slo"` section:
   ```json
   {
     "slo": {
       "system_health_score": {"target": 0.9, "window_hours": 24},
       "pillar_uptime": {"target": 0.99, "window_hours": 168},
       "fpc_cache_freshness_hours": {"target": 24, "window_hours": 48}
     }
   }
   ```

5. **Alert rules + routing** in `MatrixMonitorOrchestrator`:
   - Score drops below SLO → publish `MessageType.ALERT` on bus
   - CRITICAL triggers `EscalationLevel.CRITICAL` → human notification
   - Wire NIGHTFALL agent to receive CRITICAL alerts

### Phase 3: Dashboard — ~300 LOC new code

6. **Dashboard tile API** — extend OneDrop backend or relay server:
   - `GET /matrix/latest` → full MatrixReport JSON
   - `GET /matrix/tiles` → structured tile data (Progress, SLO, Adoption)
   - `GET /matrix/trend?metric=X&days=7` → time series

7. **Wire WATCHTOWER agent** to consume MatrixReport and generate digest/alerts

### Phase 4: Tests — ~600 LOC new tests

8. **Test the untested:**
   - `test_system_health_check.py` (~150 LOC)
   - `test_self_check_protocol.py` (~200 LOC)
   - `test_autonomous_daemon.py` (~150 LOC)
   - `test_matrix_monitor.py` (~100 LOC — the new unification layer)

---

## 9. FILES INVENTORY — COMPLETE REFERENCE

### Monitoring Python Files (13)

| # | File | LOC | Layer | Tests |
|---|------|-----|-------|-------|
| 1 | `tools/system_health_check.py` | 280 | System | NO |
| 2 | `tools/setup_wizard.py` | 222 | System | NO |
| 3 | `tools/validate_events.py` | 96 | System | Indirect |
| 4 | `ncl_agency_runtime/runtime/self_check_protocol.py` | 400 | Self-Check | NO |
| 5 | `ncl_agency_runtime/runtime/autonomous_daemon.py` | 1,100 | Daemon | NO |
| 6 | `ncl_agency_runtime/runtime/fpc_integration.py` | 406 | FPC | Indirect |
| 7 | `ncl_agency_runtime/runtime/pillar_registry.py` | 309 | NCC | YES |
| 8 | `ncl_agency_runtime/runtime/ncc_orchestrator.py` | 343 | NCC | YES |
| 9 | `ncl_agency_runtime/runtime/inter_pillar_bus.py` | ~380 | NCC | YES |
| 10 | `ncl_agency_runtime/agents/super_openclaw_agent.py` (HealthMonitor) | ~60 | Agent | YES |
| 11 | `ncl_agency_runtime/fpc/agents/__init__.py` (WATCHTOWER+roles) | 803 | FPC Agents | Partial |
| 12 | `ncl_agency_runtime/fpc/agents/stubs.py` | 411 | FPC Agents | Partial |
| 13 | `ncl_onedrop_setup/backend/api/main.py` | 24 | OneDrop | NO |

### Test Files (4)

| # | File | LOC | Covers |
|---|------|-----|--------|
| 1 | `tests/test_ncc_integration.py` | 616 | PillarRegistry, NCCOrchestrator, InterPillarBus |
| 2 | `tests/test_relay_server.py` | 437 | RateLimiter, AuthManager, /health |
| 3 | `tests/test_fpc_agent_framework.py` | 563 | WATCHTOWER, agent router |
| 4 | `tests/test_super_openclaw_agent.py` | ~200 (health portion) | HealthMonitor.check() |

### Configuration

| File | Monitoring Sections |
|------|-------------------|
| `ncl_config.json` | `network.relay_port`, `network.onedrop_port`, `access.rate_limits`, `memory.limits`, `privacy.audit_logging` |

### Documentation

| File | Content |
|------|---------|
| `ncl_onedrop_setup/docs/ops/matrix_dashboard.md` | 7-line stub — tile types only |
| `ncl_onedrop_setup/docs/product/roadmap_100_steps.md` | Steps 79, 91–100 define Matrix Monitor roadmap |
| `SYSTEM_AUDIT_COMPLETE.md` | Prior system audit — lists health monitoring as "gap filled" |

---

## 10. CONCLUSION

NCL has a **strong but fragmented monitoring foundation**. The NCC governance layer (`pillar_registry` + `ncc_orchestrator` + `inter_pillar_bus`) is production-quality and well-tested — this is the natural home for NCC Matrix Monitor.

**What NCC Matrix Monitor should be:**
1. A unification layer over 5 existing health check subsystems
2. A persistence + history layer (currently mostly ephemeral)
3. An SLO engine with error budget tracking
4. An alert routing system wired to the InterPillarBus
5. A dashboard data API for tile consumption

**What it should NOT be:**
- A rewrite of existing monitoring code
- A separate monitoring system duplicating existing checks
- An external service — keep it local-first per doctrine

**Estimated effort:** ~1,800 LOC of new code (500 unification + 400 SLO/alerts + 300 dashboard + 600 tests), leveraging ~4,871 LOC of existing monitoring infrastructure.
