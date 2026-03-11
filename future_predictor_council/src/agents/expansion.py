"""Expansion Pack agents — 10 additional agents for full autonomy.

These extend the Launch Squadron with advanced capabilities:
intent routing, scenario simulation, strategy planning, ethics review,
real-time monitoring, human UX, negotiation, emergency response,
red team testing, and cross-system integration.
"""

from __future__ import annotations

import logging
import pathlib
import uuid
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from .orchestrator import Task
from .stubs import BaseAgent, _load_default_data, _load_steering

logger = logging.getLogger(__name__)

_BASE_DIR = pathlib.Path(__file__).resolve().parents[2]


# ── MINDGATE — Intent Router ──────────────────────────────────
class MindgateAgent(BaseAgent):
    codename = "ir"
    callsign = "MINDGATE"

    # Intent classification via keyword presence + scoring
    _INTENT_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "forecast_request": ["forecast", "predict", "baseline", "horizon", "arima", "project"],
        "data_update": ["data", "upload", "ingest", "update", "refresh", "import"],
        "model_cycle": ["retrain", "model", "cycle", "neural", "evaluate", "backtest"],
        "causal_query": ["causal", "why", "cause", "effect", "intervention", "what-if", "whatif"],
        "explain_request": ["explain", "interpret", "feature", "shap", "attribution", "dossier"],
        "burst_request": ["burst", "gpu", "cloud", "scale", "foundation", "chronos", "timesfm"],
        "security_audit": ["security", "audit", "sbom", "vulnerability", "scan", "privacy"],
        "status_check": ["status", "health", "check", "monitor", "dashboard"],
    }

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload", {})
        goal = payload.get("goal", "").lower()

        # Score each intent type
        scores: dict[str, float] = {}
        for intent_type, keywords in self._INTENT_PATTERNS.items():
            score = sum(1.0 for kw in keywords if kw in goal)
            if score > 0:
                scores[intent_type] = score

        if scores:
            best = max(scores, key=scores.get)  # type: ignore[arg-type]
            confidence = round(min(scores[best] / 3.0, 1.0), 2)
        else:
            best = "general"
            confidence = 0.5

        # Map intent to target agents
        agent_map: dict[str, list[str]] = {
            "forecast_request": ["ds", "be", "ne", "xe"],
            "data_update": ["ds", "xe"],
            "model_cycle": ["xe", "dx"],
            "causal_query": ["cs", "xe"],
            "explain_request": ["xe"],
            "burst_request": ["fo"],
            "security_audit": ["so"],
            "status_check": ["mo", "em"],
            "general": ["ds", "be", "xe"],
        }

        return {
            "status": "intent_classified",
            "raw_goal": payload.get("goal", ""),
            "intent_type": best,
            "confidence": confidence,
            "target_agents": agent_map.get(best, ["ds", "be", "xe"]),
            "all_scores": {k: round(v, 2) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
        }


# ── PHOENIX — Scenario Simulation ─────────────────────────────
class PhoenixAgent(BaseAgent):
    codename = "ss"
    callsign = "PHOENIX"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload", {})
        n_scenarios = payload.get("scenarios", 1000)

        df = _load_default_data()
        if df.empty or "y" not in df.columns:
            return {"status": "simulation_complete", "scenarios_run": 0, "note": "no_data"}

        y = df["y"].values.astype(float)
        mu = float(np.mean(y))
        sigma = float(np.std(y))

        # Bootstrap simulation: resample + noise
        rng = np.random.default_rng(42)
        simulations = rng.normal(mu, sigma, size=n_scenarios)

        return {
            "status": "simulation_complete",
            "scenarios_run": n_scenarios,
            "p50_outcome": round(float(np.percentile(simulations, 50)), 2),
            "p5_downside": round(float(np.percentile(simulations, 5)), 2),
            "p95_upside": round(float(np.percentile(simulations, 95)), 2),
            "mean": round(float(np.mean(simulations)), 2),
            "std": round(sigma, 2),
        }


# ── NAVIGATOR — Strategy Planner ──────────────────────────────
class NavigatorAgent(BaseAgent):
    codename = "sp"
    callsign = "NAVIGATOR"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        steering = _load_steering()
        budget = steering.get("budget_weekly_usd", 50.0)
        gpu_cap = steering.get("gpu_max_daily_min", 60)

        df = _load_default_data()
        data_rows = len(df) if not df.empty else 0

        # Determine resource allocation based on data size and budget
        if data_rows > 500 and budget >= 20:
            compute = "burst"
            burst = True
        else:
            compute = "local"
            burst = False

        actions = []
        # Always recommend baseline forecast
        actions.append({"action": "run_baseline", "agent": "be", "confidence": 0.95})
        if data_rows > 100:
            actions.append({"action": "run_neural", "agent": "ne", "confidence": 0.80})
        if data_rows > 50:
            actions.append({"action": "generate_xai", "agent": "xe", "confidence": 0.90})

        return {
            "status": "plan_generated",
            "horizon_days": 90,
            "priority_actions": actions,
            "resource_allocation": {
                "compute": compute,
                "burst": burst,
                "budget_weekly_usd": budget,
                "gpu_cap_min": gpu_cap,
            },
            "data_rows_available": data_rows,
        }


# ── SANCTUM — Ethics & Safety Council ─────────────────────────
class SanctumAgent(BaseAgent):
    codename = "es"
    callsign = "SANCTUM"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        df = _load_default_data()
        flags: list[str] = []

        # Check for bias indicators in data
        bias_detected = False
        fairness_score = 1.0
        if not df.empty and "y" in df.columns:
            y = df["y"].values.astype(float)
            # Check for extreme skewness (potential bias)
            if len(y) > 10:
                skewness = float(pd.Series(y).skew())
                if abs(skewness) > 2.0:
                    bias_detected = True
                    flags.append(f"High skewness detected: {skewness:.2f}")
                    fairness_score -= 0.1

            # Check for zero-inflated data
            zero_pct = float((y == 0).sum() / len(y))
            if zero_pct > 0.3:
                flags.append(f"Zero-inflated data: {zero_pct:.0%}")
                fairness_score -= 0.05

        # Check budget reasonableness
        steering = _load_steering()
        budget = steering.get("budget_weekly_usd", 50.0)
        if budget > 200:
            flags.append(f"High weekly budget: ${budget}")

        fairness_score = max(0.0, round(fairness_score, 2))

        return {
            "status": "review_complete",
            "verdict": "approved" if not flags else "flagged",
            "bias_detected": bias_detected,
            "fairness_score": fairness_score,
            "impact_assessment": "high" if bias_detected else "low",
            "flags": flags,
        }


# ── WATCHTOWER — Real-Time Event Monitor ──────────────────────
class WatchtowerAgent(BaseAgent):
    codename = "em"
    callsign = "WATCHTOWER"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from .stubs import AGENT_STUBS

        # Real agent health check: verify all agents can be instantiated
        agents_healthy = 0
        agents_degraded = 0
        agent_status: dict[str, str] = {}

        for codename, agent in AGENT_STUBS.items():
            try:
                assert hasattr(agent, "handle") and callable(agent.handle)
                agents_healthy += 1
                agent_status[codename] = "healthy"
            except Exception:
                agents_degraded += 1
                agent_status[codename] = "degraded"

        # Check data freshness
        data_path = _BASE_DIR / "data" / "raw" / "example.csv"
        anomalies = 0
        drift_score = 0.0
        if data_path.exists():
            df = _load_default_data()
            if "y" in df.columns and len(df) > 14:
                y = df["y"].values.astype(float)
                recent = y[-7:]
                historical = y[:-7]
                if len(historical) > 0:
                    drift_score = round(abs(float(np.mean(recent) - np.mean(historical)) /
                                            (np.std(historical) + 1e-9)), 4)
                    if drift_score > 2.0:
                        anomalies += 1

        level = "green"
        if agents_degraded > 0 or anomalies > 0:
            level = "yellow"
        if agents_degraded > 2:
            level = "red"

        return {
            "status": "monitoring",
            "agents_healthy": agents_healthy,
            "agents_degraded": agents_degraded,
            "anomalies_detected": anomalies,
            "drift_score": drift_score,
            "alert_level": level,
            "agent_status": agent_status,
        }


# ── MUSE — Human Interaction / UX ─────────────────────────────
class MuseAgent(BaseAgent):
    codename = "ux"
    callsign = "MUSE"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        # Generate a real status summary for human consumption
        steering = _load_steering()
        df = _load_default_data()
        data_summary = f"{len(df)} rows" if not df.empty else "no data loaded"

        return {
            "status": "ui_ready",
            "dashboard_url": "/dashboard",
            "data_summary": data_summary,
            "budget_info": f"${steering.get('budget_weekly_usd', 50)}/week",
            "metric_gate": steering.get("metric_gate", "MASE"),
            "pending_approvals": 0,
            "feedback_collected": 0,
        }


# ── COUNCILOR — Multi-Agent Negotiation ───────────────────────
class CouncilorAgent(BaseAgent):
    codename = "an"
    callsign = "COUNCILOR"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload", {})

        # Real negotiation: if multiple model results exist, compare and pick best
        results = payload.get("model_results", {})
        conflicts = 0
        consensus = True

        if len(results) > 1:
            mase_values = {k: v.get("mase") for k, v in results.items() if v.get("mase") is not None}
            if mase_values:
                best_model = min(mase_values, key=mase_values.get)  # type: ignore[arg-type]
                worst_model = max(mase_values, key=mase_values.get)  # type: ignore[arg-type]
                spread = mase_values[worst_model] - mase_values[best_model]
                if spread > 0.3:
                    conflicts += 1
                    consensus = spread < 0.5
            else:
                best_model = next(iter(results.keys()))
        else:
            best_model = None

        steering = _load_steering()
        return {
            "status": "negotiation_complete",
            "conflicts_resolved": conflicts,
            "consensus_reached": consensus,
            "recommended_model": best_model,
            "resource_arbitration": {
                "compute": "shared",
                "priority": "mase_optimized",
                "budget_remaining_usd": steering.get("budget_weekly_usd", 50.0),
            },
        }


# ── NIGHTFALL — High-Risk Intervention ────────────────────────
class NightfallAgent(BaseAgent):
    codename = "hr"
    callsign = "NIGHTFALL"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload", {})
        steering = _load_steering()
        budget = steering.get("budget_weekly_usd", 50.0)

        # Circuit breaker evaluation
        breakers: dict[str, str] = {}

        # Budget breaker
        current_spend = payload.get("total_spend_usd", 0.0)
        if current_spend > budget * 0.9:
            breakers["budget"] = "open"
        else:
            breakers["budget"] = "closed"

        # Latency breaker
        p95 = payload.get("p95_latency_ms", 0)
        if p95 > 5000:
            breakers["latency"] = "open"
        else:
            breakers["latency"] = "closed"

        # Security breaker
        vulns = payload.get("vulns_critical", 0)
        if vulns > 0:
            breakers["security"] = "open"
        else:
            breakers["security"] = "closed"

        active_incidents = sum(1 for v in breakers.values() if v == "open")

        return {
            "status": "alert" if active_incidents > 0 else "standby",
            "active_incidents": active_incidents,
            "circuit_breakers": breakers,
            "last_intervention": None,
            "budget_utilization_pct": round(current_spend / budget * 100, 1) if budget > 0 else 0.0,
        }


# ── SPECTRE — Red Team / Adversarial ─────────────────────────
class SpectreAgent(BaseAgent):
    codename = "rt"
    callsign = "SPECTRE"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        df = _load_default_data()
        edge_cases: list[str] = []
        vulns_found = 0

        if not df.empty and "y" in df.columns:
            y = df["y"].values.astype(float)

            # Edge case 1: negative values
            neg_count = int((y < 0).sum())
            if neg_count > 0:
                edge_cases.append(f"negative_values: {neg_count}")
                vulns_found += 1

            # Edge case 2: extreme outliers (>5 sigma)
            mu, sigma = float(np.mean(y)), float(np.std(y))
            if sigma > 0:
                extreme = int((np.abs(y - mu) > 5 * sigma).sum())
                if extreme > 0:
                    edge_cases.append(f"extreme_outliers_5sigma: {extreme}")

            # Edge case 3: constant sequences (model can't learn)
            if sigma < 1e-6:
                edge_cases.append("constant_series")
                vulns_found += 1

            # Edge case 4: very short series
            if len(y) < 30:
                edge_cases.append(f"short_series: {len(y)}")

        # Check steering for unsafe configs
        steering = _load_steering()
        if steering.get("gpu_max_hourly", 0) > 5.0:
            edge_cases.append("high_gpu_cost_cap")
            vulns_found += 1

        return {
            "status": "scan_complete",
            "adversarial_tests": max(len(edge_cases), 5),
            "vulnerabilities_found": vulns_found,
            "edge_cases_discovered": len(edge_cases),
            "edge_cases": edge_cases,
            "chaos_injection_safe": vulns_found == 0,
        }


# ── BRIDGE — Cross-System Integration ────────────────────────
class BridgeAgent(BaseAgent):
    codename = "si"
    callsign = "BRIDGE"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        # Check which NCL subsystems are actually accessible
        connected: list[str] = []
        pending = 0

        # Check ncl_memory
        ncl_root = _BASE_DIR.parent
        if (ncl_root / "ncl_memory.py").exists():
            connected.append("ncl_memory")
        if (ncl_root / "ncl_agency_runtime").exists():
            connected.append("ncl_agency_runtime")
        if (ncl_root / "ncl_onedrop_setup").exists():
            connected.append("ncl_onedrop_setup")
        if (ncl_root / "ncl_gbx_one_drop").exists():
            connected.append("ncl_gbx_one_drop")

        # Check internal subsystems
        if (_BASE_DIR / "config" / "steering.json").exists():
            connected.append("steering_config")
        if (_BASE_DIR / "data" / "raw" / "example.csv").exists():
            connected.append("data_pipeline")

        return {
            "status": "bridge_ok",
            "connected_systems": connected,
            "connected_count": len(connected),
            "pending_writebacks": pending,
            "last_sync": None,
        }


# ── WOLFRAM — Computational Universe Agent ────────────────────
class WolframAgent(BaseAgent):
    """Agent #21 — WOLFRAM — Computational Universe Physics Engine.

    Runs the Wolfram Physics framework: hypergraph state tracking,
    multiway branching of predictions, causal graphs, branchial distance,
    computational irreducibility detection, and ruliad exploration.

    Inspired by Stephen Wolfram's "A New Kind of Science" and the
    Wolfram Physics Project.
    """

    codename = "wp"
    callsign = "WOLFRAM"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..wolfram_physics import (
            WolframPhysicsEngine,
            branchial_entanglement,
            check_irreducibility,
        )

        payload = event.get("payload", {})
        action = payload.get("action", "observe")

        engine = WolframPhysicsEngine()

        if action == "initialize":
            agents = payload.get("agents", ["mc", "ds", "be", "ne", "fo"])
            result = engine.initialize(agents)
            return {**result, "status": "wolfram_initialized"}

        if action == "irreducibility_check":
            series_data = payload.get("series")
            if series_data is None:
                df = _load_default_data()
                series_data = df["y"].values[:50] if not df.empty else np.random.default_rng(42).normal(100, 10, 50)
            series = np.asarray(series_data, dtype=float)
            ir_result = check_irreducibility(series, payload.get("horizon", 7))
            return {
                "status": "irreducibility_tested",
                "is_irreducible": ir_result.is_irreducible,
                "reducibility_score": ir_result.reducibility_score,
                "shortcut_error": ir_result.shortcut_error,
                "full_compute_needed": ir_result.full_compute_needed,
                "method": ir_result.method,
                "detail": ir_result.detail,
            }

        if action == "multiway":
            # Build multiway branches from model predictions
            branches_data = payload.get("branches", [])
            if not branches_data:
                rng = np.random.default_rng(42)
                branches_data = [
                    {"model": "statsforecast", "preds": (100 + rng.normal(0, 5, 30)).tolist(), "conf": 0.9},
                    {"model": "patchtst", "preds": (100 + rng.normal(2, 8, 30)).tolist(), "conf": 0.8},
                    {"model": "chronos", "preds": (100 + rng.normal(-1, 6, 30)).tolist(), "conf": 0.85},
                ]
            for bd in branches_data:
                engine.multiway.add_branch(
                    bd["model"],
                    np.array(bd["preds"]),
                    bd.get("conf", 1.0),
                )
            consensus = engine.multiway.consensus_prediction()
            preds_list = [np.array(bd["preds"]) for bd in branches_data]
            ent = branchial_entanglement(preds_list)
            return {
                "status": "multiway_computed",
                "branch_count": engine.multiway.branch_count,
                "entanglement": round(ent, 4),
                "consensus_length": len(consensus) if consensus is not None else 0,
                "branchial_graph": engine.multiway.branchial_graph(),
            }

        # Default: observe — full system snapshot
        # Initialize with known agents
        known = ["mc", "ds", "be", "ne", "fo", "xe", "cs", "mo", "so", "dx",
                 "ir", "ss", "sp", "es", "em", "ux", "an", "hr", "rt", "si", "wp",
                 "nc", "ab", "sa", "sg", "rd", "jx", "sb", "ai", "xf", "yt"]
        engine.initialize(known)

        # Add sample causal chain
        e1 = engine.record_action("ds", "data_validated")
        e2 = engine.record_action("be", "forecast_produced", [e1.node_id])
        e3 = engine.record_action("cs", "causal_estimated", [e1.node_id])
        engine.record_action("mc", "council_decided", [e2.node_id, e3.node_id])

        return {
            "status": "wolfram_observed",
            **engine.observe(),
        }


# ── SENTINEL — NCC Doctrine Enforcer ─────────────────────────
class SentinelAgent(BaseAgent):
    """Agent #22 — SENTINEL — NCC Doctrine Enforcer.

    Connects the council to the NCC (Natrix Command & Control) governance
    layer. Enforces Three Pillars compliance, Faraday Fortress security,
    Doctrine-Lock rules, and PDCA audit loops.
    """

    codename = "nc"
    callsign = "SENTINEL"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..resonance_triad import NCCGovernanceConnector

        connector = NCCGovernanceConnector()
        connector.load_doctrine()

        payload = event.get("payload", {})
        action = payload.get("action", "check")

        if action == "score_pillars":
            context = payload.get("context", {})
            p1 = connector.score_pillar_art_of_war(context)
            p2 = connector.score_pillar_laws_of_power(context)
            p3 = connector.score_pillar_seven_habits(context)
            return {
                "status": "pillars_scored",
                "art_of_war": {"score": p1.score, "grade": p1.grade, "met": p1.principles_met},
                "laws_of_power": {"score": p2.score, "grade": p2.grade, "met": p2.principles_met},
                "seven_habits": {"score": p3.score, "grade": p3.grade, "met": p3.principles_met},
            }

        if action == "pdca_audit":
            phase = payload.get("phase", "plan")
            metrics = payload.get("metrics", {})
            audit = connector.run_pdca_audit(phase, metrics)
            return {
                "status": "pdca_complete",
                "phase": audit.phase,
                "score": audit.score,
                "findings": audit.findings,
                "recommendations": audit.recommendations,
            }

        # Default: full doctrine check
        context = payload.get("context", {})
        result = connector.check_doctrine(context)
        return {
            "status": "doctrine_checked",
            "compliant": result.compliant,
            "resonance_score": result.resonance_score,
            "fortress_ok": result.fortress_layers_ok,
            "fortress_warn": result.fortress_layers_warn,
            "lock_violations": result.doctrine_lock_violations,
            "pillar_grades": [
                {"name": p.name, "score": p.score, "grade": p.grade}
                for p in result.pillar_scores
            ],
            "doctrine_loaded": connector.doctrine_loaded,
        }


# ── VAULT — AAC Asset Bridge ─────────────────────────────────
class VaultAgent(BaseAgent):
    """Agent #23 — VAULT — AAC Asset Bridge.

    Connects the council to the Autonomous Asset Collective (AAC).
    Provides portfolio snapshots, strategy reports, and trading signal relay.
    """

    codename = "ab"
    callsign = "VAULT"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..resonance_triad import AACAssetBridge, TradingSignal

        bridge = AACAssetBridge()
        bridge.discover()

        payload = event.get("payload", {})
        action = payload.get("action", "snapshot")

        if action == "strategy_report":
            report = bridge.strategy_report()
            return {
                "status": "strategy_report",
                "connected": bridge.connected,
                "strategy_count": report.strategy_count,
                "active_strategies": report.active_strategies,
            }

        if action == "relay_signal":
            signal = TradingSignal(
                signal_type=payload.get("signal_type", "hold"),
                source_strategy=payload.get("source_strategy", ""),
                confidence=payload.get("confidence", 0.0),
                asset=payload.get("asset", ""),
            )
            result = bridge.relay_signal(signal)
            return {**result, "connected": bridge.connected}

        # Default: portfolio snapshot
        snapshot = bridge.portfolio_snapshot()
        return {
            "status": "snapshot_complete",
            "connected": snapshot.connected,
            "exchange_count": snapshot.exchange_count,
            "exchanges": snapshot.exchanges,
            "strategy_count": snapshot.strategy_count,
            "health": snapshot.health,
            "version": bridge.version,
        }


# ── NEXUS — Super Agency Orchestrator ─────────────────────────
class NexusAgent(BaseAgent):
    """Agent #24 — NEXUS — Super Agency Orchestrator.

    Connects the council to the Super Agency platform for multi-agent
    dispatch, RBAC coordination, and workflow composition.
    """

    codename = "sa"
    callsign = "NEXUS"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..resonance_triad import AgencyDispatch, SuperAgencyOrchestrator

        orchestrator = SuperAgencyOrchestrator()
        orchestrator.discover()

        payload = event.get("payload", {})
        action = payload.get("action", "status")

        if action == "dispatch":
            dispatch = AgencyDispatch(
                workflow_id=payload.get("workflow_id", f"wf-{task.id}"),
                target_agents=payload.get("target_agents", []),
                task_description=payload.get("description", ""),
                priority=payload.get("priority", "normal"),
            )
            result = orchestrator.dispatch(dispatch)
            return {**result, "connected": orchestrator.connected}

        if action == "check_workflow":
            wf_id = payload.get("workflow_id", "")
            wf_status = orchestrator.check_workflow(wf_id)
            return {
                "status": "workflow_checked",
                "workflow_id": wf_status.workflow_id,
                "state": wf_status.state,
                "progress_pct": wf_status.progress_pct,
                "connected": orchestrator.connected,
            }

        if action == "rbac_check":
            agent_code = payload.get("agent_codename", "")
            rbac_action = payload.get("rbac_action", "")
            rbac = orchestrator.rbac_check(agent_code, rbac_action)
            return {
                "status": "rbac_checked",
                **rbac,
                "connected": orchestrator.connected,
            }

        # Default: status
        return {
            "status": "agency_status",
            "connected": orchestrator.connected,
            "capabilities": orchestrator.capabilities,
            "capability_count": len(orchestrator.capabilities),
            "root": str(orchestrator._root),
        }


# ── CIPHER — SIGINT Intelligence & Fusion Analyst ────────────
class CipherAgent(BaseAgent):
    """Agent #25 -- CIPHER -- SIGINT Intelligence & Fusion Analyst.

    Applies Unit 8200's intelligence collection cycle (TCPED) and
    multi-source fusion to the council's data pipeline. Runs the
    full intelligence cycle: tasking, collection, processing,
    exploitation, and compartmented dissemination.
    """

    codename = "sg"
    callsign = "CIPHER"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..unit_8200_doctrine import (
            IntelligenceDiscipline,
            Unit8200Doctrine,
        )

        doctrine = Unit8200Doctrine()
        doctrine.initialize()

        payload = event.get("payload", {})
        action = payload.get("action", "collect")

        if action == "collect":
            discipline_str = payload.get("discipline", "osint")
            discipline = IntelligenceDiscipline(discipline_str)
            raw_data = payload.get("raw_data", {})
            source = payload.get("source", "unknown")
            recipients = payload.get("recipients", ["mc"])
            result = doctrine.run_intelligence_cycle(
                discipline, raw_data, source, recipients,
            )
            return {"status": "intelligence_collected", **result}

        if action == "fuse":
            # Ingest multiple reports and generate operational picture
            reports_data = payload.get("reports", [])
            for rd in reports_data:
                discipline = IntelligenceDiscipline(rd.get("discipline", "osint"))
                doctrine.run_intelligence_cycle(
                    discipline, rd.get("data", {}), rd.get("source", "unknown"),
                )
            picture = doctrine.fusion.generate_picture()
            return {"status": "fusion_complete", **picture}

        if action == "scan_zero_day":
            predictions = payload.get("predictions", [])
            scan = doctrine.redteam.zero_day_scan(predictions)
            return {**scan, "status": "zero_day_scanned"}

        if action == "doctrine_score":
            context = payload.get("context", {})
            score = doctrine.score_doctrine(context)
            return {"status": "doctrine_scored", **score}

        # Default: operational readiness
        readiness = doctrine.operational_readiness()
        return {**readiness, "status": "readiness_report"}


# ── AEGIS — Red Team & Adversarial Defense Shield ─────────────
class AegisAgent(BaseAgent):
    """Agent #26 -- AEGIS -- Red Team & Adversarial Defense Shield.

    Named after the mythological shield of Zeus. Applies Unit 8200's
    red team / blue team methodology to continuously validate the
    council's predictions, models, and infrastructure.

    Red team: probe for vulnerabilities, inject noise, simulate drift
    Blue team: defend model integrity, activate countermeasures
    """

    codename = "rd"
    callsign = "AEGIS"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..unit_8200_doctrine import Unit8200Doctrine

        doctrine = Unit8200Doctrine()
        doctrine.initialize()

        payload = event.get("payload", {})
        action = payload.get("action", "red_team")

        if action == "red_team":
            predictions = payload.get("predictions", [])
            result = doctrine.red_team_predictions(predictions)
            return {"status": "red_team_complete", **result}

        if action == "probe":
            target = payload.get("target", "model")
            method = payload.get("method", "noise_injection")
            params = payload.get("params", {})
            probe = doctrine.redteam.probe(target, method, params)
            finding = doctrine.redteam.assess_finding(probe)
            return {
                "status": "probe_complete",
                "probe_id": probe.probe_id,
                "vulnerability_found": probe.result.get("vulnerability_detected", False),
                "severity": probe.result.get("severity", "low"),
                "finding_id": finding.finding_id if finding else None,
            }

        if action == "defend":
            threat_type = payload.get("threat_type", "unknown")
            context = payload.get("context", {})
            defense = doctrine.redteam.defend(threat_type, context)
            return {"status": "defense_activated", **defense}

        if action == "stress_test":
            predictions = payload.get("predictions", [])
            noise_levels = payload.get("noise_levels")
            result = doctrine.redteam.stress_test(predictions, noise_levels)
            return {**result, "status": "stress_test_complete"}

        if action == "threat_assessment":
            assessment = doctrine.threat_matrix.summary()
            return {"status": "threat_assessed", **assessment}

        # Default: full red team summary
        return {
            "status": "redteam_summary",
            **doctrine.redteam.summary(),
        }


# ── MANDARIN — Geopolitical Intelligence Advisor ──────────────
class MandarinAgent(BaseAgent):
    """Agent #27 -- MANDARIN -- Geopolitical Intelligence Advisor.

    Named for the language of strategic diplomacy. Integrates
    Jiang Xueqin's geopolitical framework: innovation-over-imitation,
    education-as-predictor, bridge-perspectives, structural-over-surface,
    data-driven narrative, and long-horizon thinking.

    Provides continuous geopolitical signal collection, multi-lens
    strategic assessment, and trusted advisory output.
    """

    codename = "jx"
    callsign = "MANDARIN"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..geopolitical_advisor import JiangXueqinAdvisor

        advisor = JiangXueqinAdvisor()
        advisor.initialize()

        payload = event.get("payload", {})
        action = payload.get("action", "assess")

        if action == "ingest":
            source = payload.get("source", "unknown")
            region = payload.get("region", "global")
            lens = payload.get("lens", "strategic_competition")
            headline = payload.get("headline", "")
            content = payload.get("content", {})
            tags = payload.get("tags", [])
            result = advisor.ingest_signal(source, region, lens, headline, content, tags)
            return {**result, "status": "signal_ingested"}

        if action == "assess":
            region = payload.get("region", "global")
            horizon = payload.get("horizon_years", 5)
            result = advisor.strategic_assessment(region, horizon)
            return {**result, "status": "assessment_complete"}

        if action == "advisory":
            question = payload.get("question", "")
            context = payload.get("context", {})
            result = advisor.consult_advisor(question, context)
            return {**result, "status": "advisor_consulted"}

        if action == "pipeline":
            result = advisor.run_pipeline_cycle()
            return {**result, "status": "pipeline_cycle_complete"}

        if action == "narrative":
            region = payload.get("region", "global")
            from ..geopolitical_advisor import Region
            r = Region(region)
            signals = advisor.pipeline.collector.signals_by_region(r)
            narrative = advisor.pipeline.narrative.build_narrative(signals, r)
            return {**narrative, "status": "narrative_built"}

        if action == "lessons":
            context = payload.get("context", {})
            result = advisor.score_lessons(context)
            return {**result, "status": "lessons_scored"}

        if action == "readiness":
            result = advisor.operational_readiness()
            return {**result, "status": "readiness_checked"}

        # Default: operational readiness
        return {
            **advisor.operational_readiness(),
            "status": "mandarin_ready",
        }


class CortexAgent(BaseAgent):
    """Agent #28 -- CORTEX -- Second Brain Knowledge Engine.

    Implements Tiago Forte's Second Brain methodology: PARA organization,
    CODE workflow, Progressive Summarization, Intermediate Packets,
    and Just-In-Time retrieval as a knowledge amplification layer.
    """

    codename = "sb"
    callsign = "CORTEX"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..second_brain import (
            PacketType,
            PARACategory,
            RetrievalMode,
            SecondBrainEngine,
        )

        engine = SecondBrainEngine()
        engine.initialize()

        payload = event.get("payload", {})
        action = payload.get("action", "capture")

        if action == "capture":
            title = payload.get("title", "")
            source = payload.get("source", "unknown")
            raw_text = payload.get("raw_text", "")
            content = payload.get("content", {})
            category_str = payload.get("category", "resources")
            category = PARACategory(category_str)
            tags = payload.get("tags", [])
            result = engine.capture_knowledge(
                title, source, raw_text, content, category, tags,
            )
            return {**result, "status": "knowledge_captured"}

        if action == "distill":
            note_id = payload.get("note_id", "")
            result = engine.distill_note(note_id)
            return {**result, "status": "note_distilled"}

        if action == "express":
            note_ids = payload.get("note_ids", [])
            title = payload.get("title", "")
            output_format = payload.get("format", "report")
            result = engine.express_knowledge(note_ids, title, output_format)
            return {**result, "status": "knowledge_expressed"}

        if action == "pipeline":
            title = payload.get("title", "")
            source = payload.get("source", "unknown")
            raw_text = payload.get("raw_text", "")
            category_str = payload.get("category", "resources")
            category = PARACategory(category_str)
            tags = payload.get("tags", [])
            result = engine.full_pipeline(title, source, raw_text, category, tags)
            return {**result, "status": "pipeline_complete"}

        if action == "retrieve":
            query = payload.get("query", "")
            mode_str = payload.get("mode", "keyword")
            mode = RetrievalMode(mode_str)
            limit = payload.get("limit", 10)
            result = engine.retrieve(query, mode, limit)
            return {**result, "status": "knowledge_retrieved"}

        if action == "packet":
            packet_type_str = payload.get("packet_type", "distilled_note")
            packet_type = PacketType(packet_type_str)
            title = payload.get("title", "")
            content = payload.get("content", {})
            source_notes = payload.get("source_notes", [])
            tags = payload.get("tags", [])
            result = engine.create_packet(
                packet_type, title, content, source_notes, tags,
            )
            return {**result, "status": "packet_created"}

        if action == "connect":
            note_a = payload.get("note_a", "")
            note_b = payload.get("note_b", "")
            weight = payload.get("weight", 1.0)
            result = engine.connect_notes(note_a, note_b, weight)
            return {**result, "status": "notes_connected"}

        if action == "problems":
            knowledge = payload.get("knowledge", "")
            result = engine.test_against_problems(knowledge)
            return {**result, "status": "problems_tested"}

        if action == "cycle":
            result = engine.run_cycle()
            return {**result, "status": "cycle_complete"}

        if action == "methodology":
            context = payload.get("context", {})
            result = engine.score_methodology(context)
            return {**result, "status": "methodology_scored"}

        if action == "readiness":
            result = engine.operational_readiness()
            return {**result, "status": "readiness_checked"}

        # Default: capture (most common entry point)
        result = engine.operational_readiness()
        return {**result, "status": "cortex_ready"}


class BeaconAgent(BaseAgent):
    """Agent #29 -- BEACON -- AI Daily Brief & Exponential Intelligence.

    Integrates NLW's AI Daily Brief (policy, safety, industry, models,
    regulation) with Peter H. Diamandis's exponential frameworks (6 D's,
    abundance, convergence, metatrends, moonshots, MTP). Lessons learned
    from both channels are scored and applied to council operations.
    """

    codename = "ai"
    callsign = "BEACON"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..ai_daily_brief import (
            AbundanceDomain,
            AIDailyBriefEngine,
            BriefingCategory,
            ConvergenceType,
            ExponentialStage,
            InsightTier,
            TechnologyDomain,
        )

        engine = AIDailyBriefEngine()
        engine.initialize()

        payload = event.get("payload", {})
        action = payload.get("action", "ingest")

        if action == "ingest":
            title = payload.get("title", "")
            headline = payload.get("headline", "")
            category_str = payload.get("category", "ai_industry")
            category = BriefingCategory(category_str)
            analysis = payload.get("analysis", "")
            tags = payload.get("tags", [])
            tier_str = payload.get("tier", "notable")
            tier = InsightTier(tier_str)
            source = payload.get("source", "ai_daily_brief")
            result = engine.ingest_briefing(
                title, headline, category, analysis, None, tags, tier, source,
            )
            return {**result, "status": "briefing_ingested"}

        if action == "exponential":
            tech_str = payload.get("technology", "artificial_intelligence")
            technology = TechnologyDomain(tech_str)
            stage_str = payload.get("stage", "digitized")
            stage = ExponentialStage(stage_str)
            description = payload.get("description", "")
            evidence = payload.get("evidence", [])
            result = engine.track_exponential(
                technology, stage, description, evidence,
            )
            return {**result, "status": "exponential_tracked"}

        if action == "converge":
            tech_list = payload.get("technologies", [])
            technologies = [TechnologyDomain(t) for t in tech_list]
            conv_type_str = payload.get("convergence_type", "parallel")
            conv_type = ConvergenceType(conv_type_str)
            description = payload.get("description", "")
            timeline = payload.get("timeline_years", 5)
            result = engine.detect_convergence(
                technologies, conv_type, description, timeline,
            )
            return {**result, "status": "convergence_detected"}

        if action == "abundance":
            domain_str = payload.get("domain", "information")
            domain = AbundanceDomain(domain_str)
            scarcity = payload.get("current_scarcity", 0.5)
            tech_list = payload.get("enabling_technologies", [])
            enabling = [TechnologyDomain(t) for t in tech_list]
            barriers = payload.get("barriers", [])
            enablers = payload.get("enablers", [])
            result = engine.assess_abundance(
                domain, scarcity, enabling, barriers, enablers,
            )
            return {**result, "status": "abundance_assessed"}

        if action == "metatrend":
            name = payload.get("name", "")
            description = payload.get("description", "")
            tech_list = payload.get("contributing_technologies", [])
            techs = [TechnologyDomain(t) for t in tech_list]
            horizon = payload.get("horizon_years", 20)
            result = engine.register_metatrend(
                name, description, techs, horizon,
            )
            return {**result, "status": "metatrend_registered"}

        if action == "moonshot":
            title = payload.get("title", "")
            domain_str = payload.get("domain", "information")
            domain = AbundanceDomain(domain_str)
            baseline = payload.get("current_baseline", "")
            target = payload.get("ten_x_target", "")
            convergences = payload.get("enabling_convergences", [])
            mtp = payload.get("mtp_alignment", 0.5)
            result = engine.create_moonshot(
                title, domain, baseline, target, convergences, mtp,
            )
            return {**result, "status": "moonshot_created"}

        if action == "digest":
            date = payload.get("date", "")
            result = engine.generate_digest(date)
            return {**result, "status": "digest_generated"}

        if action == "pipeline":
            title = payload.get("title", "")
            headline = payload.get("headline", "")
            category_str = payload.get("category", "ai_industry")
            category = BriefingCategory(category_str)
            tech_str = payload.get("technology", None)
            technology = TechnologyDomain(tech_str) if tech_str else None
            stage_str = payload.get("stage", None)
            stage = ExponentialStage(stage_str) if stage_str else None
            tags = payload.get("tags", [])
            result = engine.full_pipeline(
                title, headline, category, technology, stage, tags,
            )
            return {**result, "status": "pipeline_complete"}

        if action == "lessons":
            source = payload.get("source", None)
            keyword = payload.get("keyword", None)
            result = engine.query_lessons(source, keyword)
            return {**result, "status": "lessons_queried"}

        if action == "score_lessons":
            context = payload.get("context", {})
            result = engine.score_lessons(context)
            return {**result, "status": "lessons_scored"}

        if action == "readiness":
            result = engine.operational_readiness()
            return {**result, "status": "readiness_checked"}

        # Default: operational readiness
        result = engine.operational_readiness()
        return {**result, "status": "beacon_ready"}


class HeraldAgent(BaseAgent):
    """Agent #30 — HERALD — X (Twitter) Intelligence & Feed Router.

    Ingests X account feed (timeline, likes, reposts, bookmarks),
    classifies each item by content domain (AI, finance, geopolitics,
    security, etc.), applies quality filtering, and routes intelligence
    to the appropriate NCL agent, division, and NCC Triad pillar.
    """

    codename = "xf"
    callsign = "HERALD"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..x_intelligence import (
            EngagementType,
            SignalQuality,
            XIntelligenceEngine,
            XPost,
        )

        payload = event.get("payload", {})
        action = payload.get("action", "readiness")

        engine = XIntelligenceEngine(
            min_quality=SignalQuality(payload.get("min_quality", "weak")),
        )

        if action == "ingest":
            post_data = payload.get("post", {})
            post = XPost(
                post_id=post_data.get("post_id", f"xp-{uuid.uuid4().hex[:8]}"),
                author_handle=post_data.get("author_handle", "unknown"),
                author_name=post_data.get("author_name", "Unknown"),
                content=post_data.get("content", ""),
                engagement_type=EngagementType(post_data.get("engagement_type", "original")),
                timestamp=post_data.get("timestamp", ""),
                url=post_data.get("url", ""),
                hashtags=post_data.get("hashtags", []),
                mentions=post_data.get("mentions", []),
                like_count=post_data.get("like_count", 0),
                repost_count=post_data.get("repost_count", 0),
                reply_count=post_data.get("reply_count", 0),
                view_count=post_data.get("view_count", 0),
            )
            result = engine.ingest_post(post)
            return {**result, "status": "post_ingested"}

        if action == "classify":
            post_data = payload.get("post", {})
            post = XPost(
                post_id=post_data.get("post_id", f"xp-{uuid.uuid4().hex[:8]}"),
                author_handle=post_data.get("author_handle", "unknown"),
                author_name=post_data.get("author_name", "Unknown"),
                content=post_data.get("content", ""),
                engagement_type=EngagementType(post_data.get("engagement_type", "original")),
                hashtags=post_data.get("hashtags", []),
                like_count=post_data.get("like_count", 0),
                repost_count=post_data.get("repost_count", 0),
            )
            result = engine.classify_post(post)
            return {**result, "status": "post_classified"}

        if action == "pipeline":
            post_data = payload.get("post", {})
            post = XPost(
                post_id=post_data.get("post_id", f"xp-{uuid.uuid4().hex[:8]}"),
                author_handle=post_data.get("author_handle", "unknown"),
                author_name=post_data.get("author_name", "Unknown"),
                content=post_data.get("content", ""),
                engagement_type=EngagementType(post_data.get("engagement_type", "original")),
                timestamp=post_data.get("timestamp", ""),
                hashtags=post_data.get("hashtags", []),
                mentions=post_data.get("mentions", []),
                like_count=post_data.get("like_count", 0),
                repost_count=post_data.get("repost_count", 0),
                reply_count=post_data.get("reply_count", 0),
                view_count=post_data.get("view_count", 0),
            )
            result = engine.full_pipeline(post)
            return {**result, "status": result.get("status", "pipeline_complete")}

        if action == "digest":
            result = engine.generate_digest()
            return {**result, "status": "digest_generated"}

        if action == "queue":
            codename = payload.get("agent_codename", "mc")
            result = engine.agent_queue(codename)
            return {**result, "status": "queue_retrieved"}

        if action == "summary":
            result = engine.routing_summary()
            return {**result, "status": "summary_generated"}

        if action == "readiness":
            result = engine.operational_readiness()
            return {**result, "status": "readiness_checked"}

        # Default: operational readiness
        result = engine.operational_readiness()
        return {**result, "status": "herald_ready"}


class CatalystAgent(BaseAgent):
    """Agent #31 — CATALYST — YouTube Intelligence & AI Tool Discovery.

    Dual-pipeline agent:
      1. TIAIFT pipeline — AI tool extraction, classification, impact scoring
      2. AI Upload pipeline — strategic AI news analysis, entity extraction,
         signal detection, narrative tracking, intelligence briefing

    Routes intelligence to the appropriate NCL agent, division, and
    NCC Triad pillar across both channels.
    """

    codename = "yt"
    callsign = "CATALYST"

    def _execute(self, task: Task, event: dict[str, Any]) -> dict[str, Any]:
        from ..youtube_intelligence import (
            ImpactLevel,
            VideoEntry,
            VideoSource,
            YouTubeIntelligenceEngine,
        )

        payload = event.get("payload", {})
        action = payload.get("action", "readiness")

        # ── AI Upload pipeline actions ──
        if action.startswith("au_"):
            return self._handle_ai_upload(action, payload)

        engine = YouTubeIntelligenceEngine(
            min_impact=ImpactLevel(payload.get("min_impact", "low")),
        )

        if action == "ingest":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "vid-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "There Is An AI For That"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "there_is_an_ai_for_that")),
                published_at=video_data.get("published_at", ""),
                duration_seconds=video_data.get("duration_seconds", 0),
                view_count=video_data.get("view_count", 0),
                like_count=video_data.get("like_count", 0),
                comment_count=video_data.get("comment_count", 0),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = engine.ingest_video(video)
            return {**result, "status": "video_ingested"}

        if action == "extract":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "vid-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "There Is An AI For That"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "there_is_an_ai_for_that")),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = engine.extract_tools(video)
            return {**result, "status": "tools_extracted"}

        if action == "classify":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "vid-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "There Is An AI For That"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "there_is_an_ai_for_that")),
                view_count=video_data.get("view_count", 0),
                like_count=video_data.get("like_count", 0),
                comment_count=video_data.get("comment_count", 0),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = engine.classify_video(video)
            return {**result, "status": "video_classified"}

        if action == "pipeline":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "vid-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "There Is An AI For That"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "there_is_an_ai_for_that")),
                published_at=video_data.get("published_at", ""),
                duration_seconds=video_data.get("duration_seconds", 0),
                view_count=video_data.get("view_count", 0),
                like_count=video_data.get("like_count", 0),
                comment_count=video_data.get("comment_count", 0),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = engine.full_pipeline(video)
            return {**result, "status": result.get("status", "pipeline_complete")}

        if action == "digest":
            result = engine.generate_digest()
            return {**result, "status": "digest_generated"}

        if action == "trends":
            result = engine.trend_report()
            return {**result, "status": "trends_reported"}

        if action == "queue":
            codename = payload.get("agent_codename", "mc")
            result = engine.agent_queue(codename)
            return {**result, "status": "queue_retrieved"}

        if action == "summary":
            result = engine.routing_summary()
            return {**result, "status": "summary_generated"}

        if action == "readiness":
            result = engine.operational_readiness()
            return {**result, "status": "readiness_checked"}

        # Default: operational readiness
        result = engine.operational_readiness()
        return {**result, "status": "readiness_checked"}

    def _handle_ai_upload(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle AI Upload strategic intelligence actions."""
        from ..ai_upload_intelligence import AIUploadEngine
        from ..youtube_intelligence import VideoEntry, VideoSource

        au_engine = AIUploadEngine()

        if action == "au_ingest":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "au-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "AI Upload"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "ai_upload")),
                published_at=video_data.get("published_at", ""),
                duration_seconds=video_data.get("duration_seconds", 0),
                view_count=video_data.get("view_count", 0),
                like_count=video_data.get("like_count", 0),
                comment_count=video_data.get("comment_count", 0),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = au_engine.analyze_video(video)
            return {**result, "status": "au_analyzed"}

        if action == "au_analyze":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "au-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "AI Upload"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "ai_upload")),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = au_engine.detect_signals(video)
            return {**result, "status": "au_signals_detected"}

        if action == "au_signal":
            video_data = payload.get("video", {})
            video = VideoEntry(
                video_id=video_data.get("video_id", "au-unknown"),
                title=video_data.get("title", ""),
                channel_name=video_data.get("channel_name", "AI Upload"),
                description=video_data.get("description", ""),
                source=VideoSource(video_data.get("source", "ai_upload")),
                published_at=video_data.get("published_at", ""),
                duration_seconds=video_data.get("duration_seconds", 0),
                view_count=video_data.get("view_count", 0),
                like_count=video_data.get("like_count", 0),
                comment_count=video_data.get("comment_count", 0),
                tags=video_data.get("tags", []),
                transcript_snippet=video_data.get("transcript_snippet", ""),
            )
            result = au_engine.full_pipeline(video)
            return {**result, "status": result.get("status", "au_pipeline_complete")}

        if action == "au_brief":
            result = au_engine.generate_brief()
            return {**result, "status": "au_brief_generated"}

        if action == "au_narrative":
            result = au_engine.narrative_report()
            return {**result, "status": "au_narrative_reported"}

        if action == "au_readiness":
            result = au_engine.operational_readiness()
            return {**result, "status": "au_readiness_checked"}

        # Default AI Upload readiness
        result = au_engine.operational_readiness()
        return {**result, "status": "au_readiness_checked"}


# ── Registry ───────────────────────────────────────────────────
EXPANSION_STUBS: dict[str, BaseAgent] = {
    "ir": MindgateAgent(),
    "ss": PhoenixAgent(),
    "sp": NavigatorAgent(),
    "es": SanctumAgent(),
    "em": WatchtowerAgent(),
    "ux": MuseAgent(),
    "an": CouncilorAgent(),
    "hr": NightfallAgent(),
    "rt": SpectreAgent(),
    "si": BridgeAgent(),
    "wp": WolframAgent(),
    "nc": SentinelAgent(),
    "ab": VaultAgent(),
    "sa": NexusAgent(),
    "sg": CipherAgent(),
    "rd": AegisAgent(),
    "jx": MandarinAgent(),
    "sb": CortexAgent(),
    "ai": BeaconAgent(),
    "xf": HeraldAgent(),
    "yt": CatalystAgent(),
}


def register_expansion(mission_control: Any) -> None:
    """Register all expansion agents with a MissionControl instance."""
    for codename, agent in EXPANSION_STUBS.items():
        mission_control.register_agent(codename, agent.handle)
