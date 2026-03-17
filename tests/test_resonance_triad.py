"""Tests for the Resonance Energy Triad: NCC x BRS x AAC integration.

Covers: NCCGovernanceConnector, AACAssetBridge, BRSOrchestrator,
ResonanceTriad engine, triad EventTypes, and all three triad agents.
"""

from __future__ import annotations

import pathlib

# ── NCCGovernanceConnector Tests ────────────────────────────────


class TestNCCGovernanceConnector:
    def test_load_doctrine_real(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        # The real doctrine file exists in the NCL root
        result = conn.load_doctrine()
        assert result is True
        assert conn.doctrine_loaded is True
        assert len(conn.doctrine_hash) == 16

    def test_load_doctrine_missing(self, tmp_path: pathlib.Path):
        import ncl_agency_runtime.fpc.resonance_triad as mod
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        original = mod._DOCTRINE_PATH
        mod._DOCTRINE_PATH = tmp_path / "nonexistent.md"
        try:
            conn = NCCGovernanceConnector()
            result = conn.load_doctrine()
            assert result is False
            assert conn.doctrine_loaded is False
            assert conn.doctrine_hash == ""
        finally:
            mod._DOCTRINE_PATH = original

    def test_score_pillar_art_of_war_full(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        context = {
            "adaptive_routing": True,
            "within_rate_limits": True,
            "proactive_briefs": True,
            "memory_analytics": True,
            "zero_trust_enabled": True,
            "golden_tasks_passing": True,
            "five_factors_applied": True,
        }
        score = conn.score_pillar_art_of_war(context)
        assert score.name == "Art of War"
        assert score.score == 1.0
        assert score.grade == "S"
        assert len(score.principles_met) == 7
        assert len(score.principles_violated) == 0

    def test_score_pillar_art_of_war_partial(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        context = {"adaptive_routing": True, "within_rate_limits": True}
        score = conn.score_pillar_art_of_war(context)
        assert 0.0 < score.score < 1.0
        assert "terrain_awareness" in score.principles_met
        assert "win_without_fighting" in score.principles_violated

    def test_score_pillar_art_of_war_empty(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        score = conn.score_pillar_art_of_war({})
        # within_rate_limits, zero_trust_enabled, golden_tasks_passing default to True
        assert score.score > 0.0
        assert "speed_decisive" in score.principles_met

    def test_score_pillar_laws_of_power_full(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        context = {
            "policy_gate_active": True,
            "minimal_responses": True,
            "audit_trails": True,
            "kill_switch_ready": True,
            "self_healing": True,
            "retry_logic": True,
            "full_lifecycle": True,
            "rate_limiting": True,
            "graceful_degradation": True,
            "auth_required": True,
            "plugin_architecture": True,
        }
        score = conn.score_pillar_laws_of_power(context)
        assert score.score == 1.0
        assert score.grade == "S"
        assert len(score.principles_met) == 11

    def test_score_pillar_laws_of_power_none(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        score = conn.score_pillar_laws_of_power({})
        assert score.score == 0.0
        assert score.grade == "F"
        assert len(score.principles_violated) == 11

    def test_score_pillar_seven_habits_full(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        context = {
            "health_monitor_active": True,
            "mission_output_defined": True,
            "priority_queues": True,
            "memory_consolidation": True,
            "context_first_search": True,
            "event_bus_active": True,
            "learning_engine_active": True,
        }
        score = conn.score_pillar_seven_habits(context)
        assert score.score == 1.0
        assert score.grade == "S"
        assert len(score.principles_met) == 7

    def test_score_pillar_seven_habits_partial(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        context = {"health_monitor_active": True, "event_bus_active": True}
        score = conn.score_pillar_seven_habits(context)
        assert 0.0 < score.score < 1.0
        assert "be_proactive" in score.principles_met
        assert "synergize" in score.principles_met
        assert "sharpen_saw" in score.principles_violated

    def test_check_doctrine_compliant(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        conn.load_doctrine()
        # Strong context — all pillars and fortress layers
        context = {
            "adaptive_routing": True, "within_rate_limits": True, "proactive_briefs": True,
            "memory_analytics": True, "zero_trust_enabled": True, "golden_tasks_passing": True,
            "five_factors_applied": True,
            "policy_gate_active": True, "minimal_responses": True, "audit_trails": True,
            "kill_switch_ready": True, "self_healing": True, "retry_logic": True,
            "full_lifecycle": True, "rate_limiting": True, "graceful_degradation": True,
            "auth_required": True, "plugin_architecture": True,
            "health_monitor_active": True, "mission_output_defined": True, "priority_queues": True,
            "memory_consolidation": True, "context_first_search": True, "event_bus_active": True,
            "learning_engine_active": True,
            "fortress_outer_wall": True, "fortress_gatehouse": True, "fortress_courtyard": True,
            "fortress_armory": True, "fortress_watchtowers": True, "fortress_infirmary": True,
            "fortress_war_room": True, "fortress_vault": True,
        }
        result = conn.check_doctrine(context)
        assert result.compliant is True
        assert result.resonance_score > 0.9
        assert len(result.pillar_scores) == 3
        assert len(result.fortress_layers_ok) == 8
        assert len(result.doctrine_lock_violations) == 0

    def test_check_doctrine_violations(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        conn.load_doctrine()
        context = {"cloud_data_present": True, "raw_content_captured": True}
        result = conn.check_doctrine(context)
        assert result.compliant is False
        assert "zero_cloud_data" in result.doctrine_lock_violations
        assert "privacy_first" in result.doctrine_lock_violations

    def test_check_doctrine_no_fortress(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        conn.load_doctrine()
        result = conn.check_doctrine({})
        # No fortress layers → low resonance
        assert result.resonance_score < 0.5
        assert len(result.fortress_layers_warn) == 8

    def test_pdca_audit_plan(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        audit = conn.run_pdca_audit("plan", {
            "insights_queued": 10,
            "missions_planned": 5,
            "risk_assessed": True,
            "resources_allocated": True,
        })
        assert audit.phase == "plan"
        assert audit.score == 1.0
        assert len(audit.findings) == 4
        assert len(audit.recommendations) == 0

    def test_pdca_audit_do(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        audit = conn.run_pdca_audit("do", {"missions_executed": 3, "success_rate": 0.9})
        assert audit.phase == "do"
        assert audit.score > 0.5
        assert "missions_executed=3" in audit.findings

    def test_pdca_audit_check(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        audit = conn.run_pdca_audit("check", {
            "audit_complete": True, "metrics_reviewed": True, "anomalies_flagged": True,
        })
        assert audit.phase == "check"
        assert audit.score == 1.0

    def test_pdca_audit_act(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        audit = conn.run_pdca_audit("act", {
            "improvements_applied": 3, "release_notes": True, "doctrine_updated": True,
        })
        assert audit.phase == "act"
        assert audit.score == 1.0

    def test_pdca_audit_low_score_has_recommendations(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        audit = conn.run_pdca_audit("plan", {})
        assert audit.score == 0.0
        assert len(audit.recommendations) > 0

    def test_connector_summary_loaded(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        conn.load_doctrine()
        s = conn.summary()
        assert s["status"] == "loaded"
        assert s["fortress_layers"] == 8
        assert len(s["pillars"]) == 3

    def test_connector_summary_disconnected(self):
        from ncl_agency_runtime.fpc.resonance_triad import NCCGovernanceConnector

        conn = NCCGovernanceConnector()
        s = conn.summary()
        assert s["status"] == "disconnected"

    def test_pillar_score_grades(self):
        from ncl_agency_runtime.fpc.resonance_triad import PillarScore

        assert PillarScore("test", 1.0).grade == "S"
        assert PillarScore("test", 0.9).grade == "S"
        assert PillarScore("test", 0.85).grade == "A"
        assert PillarScore("test", 0.75).grade == "B"
        assert PillarScore("test", 0.65).grade == "C"
        assert PillarScore("test", 0.55).grade == "D"
        assert PillarScore("test", 0.4).grade == "F"
        assert PillarScore("test", 0.0).grade == "F"


# ── AACAssetBridge Tests ───────────────────────────────────────


class TestAACAssetBridge:
    def test_discover_missing(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        bridge = AACAssetBridge(aac_root=tmp_path / "nonexistent")
        assert bridge.discover() is False
        assert bridge.connected is False
        assert bridge.version == ""

    def test_discover_exists(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        aac = tmp_path / "aac"
        aac.mkdir()
        bridge = AACAssetBridge(aac_root=aac)
        assert bridge.discover() is True
        assert bridge.connected is True

    def test_discover_with_version(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        aac = tmp_path / "aac"
        aac.mkdir()
        (aac / "VERSION").write_text("2.7.0")
        bridge = AACAssetBridge(aac_root=aac)
        bridge.discover()
        assert bridge.version == "2.7.0"

    def test_portfolio_snapshot_disconnected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        bridge = AACAssetBridge(aac_root=tmp_path / "no")
        snapshot = bridge.portfolio_snapshot()
        assert snapshot.connected is False
        assert snapshot.health == "disconnected"

    def test_portfolio_snapshot_connected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        aac = tmp_path / "aac"
        aac.mkdir()
        # Create exchange dirs
        for ex in ["binance", "kraken"]:
            (aac / "exchanges" / ex).mkdir(parents=True)
        # Create strategy files
        strat_dir = aac / "strategies"
        strat_dir.mkdir()
        (strat_dir / "momentum.py").write_text("# strategy")
        (strat_dir / "mean_reversion.py").write_text("# strategy")

        bridge = AACAssetBridge(aac_root=aac)
        bridge.discover()
        snapshot = bridge.portfolio_snapshot()
        assert snapshot.connected is True
        assert snapshot.exchange_count == 2
        assert "binance" in snapshot.exchanges
        assert "kraken" in snapshot.exchanges
        assert snapshot.strategy_count == 2
        assert snapshot.health == "discovered"

    def test_strategy_report_disconnected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        bridge = AACAssetBridge(aac_root=tmp_path / "no")
        report = bridge.strategy_report()
        assert report.strategy_count == 0

    def test_strategy_report_connected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        aac = tmp_path / "aac"
        strat = aac / "strategies"
        strat.mkdir(parents=True)
        (strat / "alpha.py").write_text("# strategy")
        (strat / "beta.py").write_text("# strategy")
        (strat / "__init__.py").write_text("")  # Should be excluded

        bridge = AACAssetBridge(aac_root=aac)
        bridge.discover()
        report = bridge.strategy_report()
        assert report.strategy_count == 2
        assert "alpha" in report.active_strategies
        assert "beta" in report.active_strategies

    def test_relay_signal_disconnected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge, TradingSignal

        bridge = AACAssetBridge(aac_root=tmp_path / "no")
        result = bridge.relay_signal(TradingSignal(signal_type="buy"))
        assert result["status"] == "relay_failed"

    def test_relay_signal_connected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge, TradingSignal

        aac = tmp_path / "aac"
        aac.mkdir()
        bridge = AACAssetBridge(aac_root=aac)
        bridge.discover()
        signal = TradingSignal(signal_type="buy", source_strategy="momentum", confidence=0.85, asset="BTC")
        result = bridge.relay_signal(signal)
        assert result["status"] == "signal_relayed"
        assert result["signal_type"] == "buy"
        assert result["confidence"] == 0.85

    def test_bridge_summary(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AACAssetBridge

        aac = tmp_path / "aac"
        aac.mkdir()
        bridge = AACAssetBridge(aac_root=aac)
        bridge.discover()
        s = bridge.summary()
        assert s["status"] == "connected"
        assert s["known_exchanges"] == 8


# ── BRSOrchestrator Tests ──────────────────────────────


class TestBRSOrchestrator:
    def test_discover_missing(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        orch = BRSOrchestrator(sa_root=tmp_path / "no")
        assert orch.discover() is False
        assert orch.connected is False

    def test_discover_exists(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        sa = tmp_path / "sa"
        sa.mkdir()
        orch = BRSOrchestrator(sa_root=sa)
        assert orch.discover() is True
        assert orch.connected is True

    def test_discover_with_capabilities(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        sa = tmp_path / "sa"
        for d in ["agents", "skills", "workflows", "tools"]:
            (sa / d).mkdir(parents=True)

        orch = BRSOrchestrator(sa_root=sa)
        orch.discover()
        assert len(orch.capabilities) == 4
        assert "agents" in orch.capabilities
        assert "workflows" in orch.capabilities

    def test_dispatch_disconnected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AgencyDispatch, BRSOrchestrator

        orch = BRSOrchestrator(sa_root=tmp_path / "no")
        result = orch.dispatch(AgencyDispatch(workflow_id="wf-1"))
        assert result["status"] == "dispatch_failed"

    def test_dispatch_connected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import AgencyDispatch, BRSOrchestrator

        sa = tmp_path / "sa"
        sa.mkdir()
        orch = BRSOrchestrator(sa_root=sa)
        orch.discover()
        result = orch.dispatch(AgencyDispatch(
            workflow_id="wf-42",
            target_agents=["agent_a", "agent_b"],
            priority="high",
        ))
        assert result["status"] == "dispatched"
        assert result["workflow_id"] == "wf-42"
        assert result["priority"] == "high"

    def test_check_workflow_disconnected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        orch = BRSOrchestrator(sa_root=tmp_path / "no")
        status = orch.check_workflow("wf-1")
        assert status.state == "disconnected"

    def test_check_workflow_connected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        sa = tmp_path / "sa"
        sa.mkdir()
        orch = BRSOrchestrator(sa_root=sa)
        orch.discover()
        status = orch.check_workflow("wf-42")
        assert status.workflow_id == "wf-42"
        assert status.state == "pending"

    def test_rbac_check_disconnected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        orch = BRSOrchestrator(sa_root=tmp_path / "no")
        result = orch.rbac_check("mc", "dispatch")
        assert result["allowed"] is False

    def test_rbac_check_connected(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        sa = tmp_path / "sa"
        sa.mkdir()
        orch = BRSOrchestrator(sa_root=sa)
        orch.discover()
        result = orch.rbac_check("mc", "dispatch")
        assert result["allowed"] is True
        assert result["policy"] == "council_trusted"

    def test_orchestrator_summary(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import BRSOrchestrator

        sa = tmp_path / "sa"
        (sa / "agents").mkdir(parents=True)
        orch = BRSOrchestrator(sa_root=sa)
        orch.discover()
        s = orch.summary()
        assert s["status"] == "connected"
        assert s["capability_count"] == 1


# ── ResonanceTriad Engine Tests ────────────────────────────────


class TestResonanceTriad:
    def test_initialize_all_disconnected(self, tmp_path: pathlib.Path):
        import ncl_agency_runtime.fpc.resonance_triad as mod
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        original = mod._DOCTRINE_PATH
        mod._DOCTRINE_PATH = tmp_path / "no.md"
        try:
            triad = ResonanceTriad(
                ncc=NCCGovernanceConnector(),
                aac=AACAssetBridge(aac_root=tmp_path / "no_aac"),
                agency=BRSOrchestrator(sa_root=tmp_path / "no_sa"),
            )
            result = triad.initialize()
            assert result["ncc"] is False
            assert result["aac"] is False
            assert result["agency"] is False
        finally:
            mod._DOCTRINE_PATH = original

    def test_initialize_ncc_only(self):
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        triad = ResonanceTriad(
            ncc=NCCGovernanceConnector(),
            aac=AACAssetBridge(aac_root=pathlib.Path("/nonexistent/aac")),
            agency=BRSOrchestrator(sa_root=pathlib.Path("/nonexistent/sa")),
        )
        result = triad.initialize()
        assert result["ncc"] is True
        assert result["aac"] is False
        assert result["agency"] is False

    def test_compute_resonance_all_disconnected(self, tmp_path: pathlib.Path):
        import ncl_agency_runtime.fpc.resonance_triad as mod
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        original = mod._DOCTRINE_PATH
        mod._DOCTRINE_PATH = tmp_path / "no.md"
        try:
            triad = ResonanceTriad(
                ncc=NCCGovernanceConnector(),
                aac=AACAssetBridge(aac_root=tmp_path / "no"),
                agency=BRSOrchestrator(sa_root=tmp_path / "no2"),
            )
            triad.initialize()
            res = triad.compute_resonance({})
            assert res["resonance_energy"] == 0.0
            assert res["pillars_connected"] == 0
        finally:
            mod._DOCTRINE_PATH = original

    def test_compute_resonance_partial(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        # NCC connected (real doctrine), others disconnected
        triad = ResonanceTriad(
            ncc=NCCGovernanceConnector(),
            aac=AACAssetBridge(aac_root=tmp_path / "no"),
            agency=BRSOrchestrator(sa_root=tmp_path / "no2"),
        )
        triad.initialize()
        res = triad.compute_resonance({
            "within_rate_limits": True,
            "zero_trust_enabled": True,
            "golden_tasks_passing": True,
            "fortress_outer_wall": True,
            "fortress_gatehouse": True,
        })
        # NCC connected with some fortress layers → score > 0
        assert res["ncc_score"] > 0.0
        assert res["pillars_connected"] == 1

    def test_compute_resonance_full(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        # Set up AAC with exchanges and strategies
        aac = tmp_path / "aac"
        for ex in ["binance", "coinbase", "kraken", "ibkr", "ndax", "moomoo", "noxirise", "metalx"]:
            (aac / "exchanges" / ex).mkdir(parents=True)
        strat = aac / "strategies"
        strat.mkdir(parents=True)
        for i in range(52):
            (strat / f"strat_{i}.py").write_text("# strat")

        # Set up BRS with all capability dirs
        sa = tmp_path / "sa"
        for d in ["agents", "skills", "workflows", "tools"]:
            (sa / d).mkdir(parents=True)

        triad = ResonanceTriad(
            ncc=NCCGovernanceConnector(),
            aac=AACAssetBridge(aac_root=aac),
            agency=BRSOrchestrator(sa_root=sa),
        )
        triad.initialize()

        # Full context
        context = {
            "adaptive_routing": True, "within_rate_limits": True, "proactive_briefs": True,
            "memory_analytics": True, "zero_trust_enabled": True, "golden_tasks_passing": True,
            "five_factors_applied": True,
            "policy_gate_active": True, "minimal_responses": True, "audit_trails": True,
            "kill_switch_ready": True, "self_healing": True, "retry_logic": True,
            "full_lifecycle": True, "rate_limiting": True, "graceful_degradation": True,
            "auth_required": True, "plugin_architecture": True,
            "health_monitor_active": True, "mission_output_defined": True, "priority_queues": True,
            "memory_consolidation": True, "context_first_search": True, "event_bus_active": True,
            "learning_engine_active": True,
            "fortress_outer_wall": True, "fortress_gatehouse": True, "fortress_courtyard": True,
            "fortress_armory": True, "fortress_watchtowers": True, "fortress_infirmary": True,
            "fortress_war_room": True, "fortress_vault": True,
        }
        res = triad.compute_resonance(context)
        assert res["resonance_energy"] > 0.5
        assert res["pillars_connected"] == 3
        assert res["doctrine_compliant"] is True
        assert res["ncc_score"] > 0.8
        assert res["aac_score"] > 0.8
        assert res["agency_score"] == 1.0

    def test_health(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        sa = tmp_path / "sa"
        sa.mkdir()
        triad = ResonanceTriad(
            ncc=NCCGovernanceConnector(),
            aac=AACAssetBridge(aac_root=tmp_path / "no"),
            agency=BRSOrchestrator(sa_root=sa),
        )
        triad.initialize()
        h = triad.health()
        assert h["total_pillars"] == 3
        assert h["pillars_active"] == 2  # NCC + agency
        assert h["ncc"]["status"] == "loaded"
        assert h["aac"]["status"] == "disconnected"
        assert h["agency"]["status"] == "connected"

    def test_full_report(self, tmp_path: pathlib.Path):
        from ncl_agency_runtime.fpc.resonance_triad import (
            AACAssetBridge,
            NCCGovernanceConnector,
            ResonanceTriad,
            BRSOrchestrator,
        )

        triad = ResonanceTriad(
            ncc=NCCGovernanceConnector(),
            aac=AACAssetBridge(aac_root=tmp_path / "no"),
            agency=BRSOrchestrator(sa_root=tmp_path / "no2"),
        )
        triad.initialize()
        report = triad.full_report({"missions_executed": 5, "success_rate": 0.9})
        assert "resonance" in report
        assert "health" in report
        assert "pdca" in report
        assert "triad_formula" in report
        assert report["pdca"]["do"]["score"] > 0.0

    def test_default_init(self):
        from ncl_agency_runtime.fpc.resonance_triad import ResonanceTriad

        triad = ResonanceTriad()
        assert triad.ncc is not None
        assert triad.aac is not None
        assert triad.agency is not None


# ── Triad EventType Tests ──────────────────────────────────────


class TestTriadEventTypes:
    def test_ncc_event_types_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType

        assert EventType.NCC_DOCTRINE_CHECK == "ncc.doctrine_check"
        assert EventType.NCC_PILLAR_SCORE == "ncc.pillar_score"
        assert EventType.NCC_PDCA_AUDIT == "ncc.pdca_audit"

    def test_aac_event_types_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType

        assert EventType.AAC_PORTFOLIO_SYNC == "aac.portfolio_sync"
        assert EventType.AAC_SIGNAL_RELAY == "aac.signal_relay"
        assert EventType.AAC_STRATEGY_REPORT == "aac.strategy_report"

    def test_agency_event_types_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType

        assert EventType.AGENCY_DISPATCH == "agency.dispatch"
        assert EventType.AGENCY_WORKFLOW == "agency.workflow"
        assert EventType.AGENCY_GOVERNANCE == "agency.governance"

    def test_triad_resonance_event_type(self):
        from ncl_agency_runtime.fpc.agents.events import EventType

        assert EventType.TRIAD_RESONANCE == "triad.resonance"

    def test_all_triad_event_types_in_enum(self):
        from ncl_agency_runtime.fpc.agents.events import EventType

        types = [e.value for e in EventType]
        triad_types = [
            "ncc.doctrine_check", "ncc.pillar_score", "ncc.pdca_audit",
            "aac.portfolio_sync", "aac.signal_relay", "aac.strategy_report",
            "agency.dispatch", "agency.workflow", "agency.governance",
            "triad.resonance",
        ]
        for tt in triad_types:
            assert tt in types, f"Missing triad event type: {tt}"


# ── Triad Agent Tests ─────────────────────────────────────────


class TestSentinelAgent:
    def test_default_doctrine_check(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["nc"]
        task = Task("T-nc", "nc", "Check doctrine")
        result = agent.handle(task, {"payload": {}})
        assert result["status"] == "doctrine_checked"
        assert "compliant" in result
        assert "doctrine_loaded" in result
        assert result["_callsign"] == "SENTINEL"

    def test_score_pillars(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["nc"]
        task = Task("T-nc-p", "nc", "Score pillars")
        context = {
            "adaptive_routing": True,
            "within_rate_limits": True,
            "policy_gate_active": True,
            "health_monitor_active": True,
        }
        result = agent.handle(task, {"payload": {"action": "score_pillars", "context": context}})
        assert result["status"] == "pillars_scored"
        assert "art_of_war" in result
        assert "laws_of_power" in result
        assert "seven_habits" in result
        assert "score" in result["art_of_war"]
        assert "grade" in result["art_of_war"]

    def test_pdca_audit(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["nc"]
        task = Task("T-nc-a", "nc", "PDCA audit")
        result = agent.handle(task, {"payload": {
            "action": "pdca_audit",
            "phase": "do",
            "metrics": {"missions_executed": 5, "success_rate": 0.8},
        }})
        assert result["status"] == "pdca_complete"
        assert result["phase"] == "do"
        assert result["score"] > 0.0


class TestVaultAgent:
    def test_default_snapshot(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["ab"]
        task = Task("T-ab", "ab", "Portfolio snapshot")
        result = agent.handle(task, {"payload": {}})
        assert result["status"] == "snapshot_complete"
        assert "connected" in result
        assert "exchange_count" in result
        assert result["_callsign"] == "VAULT"

    def test_strategy_report(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["ab"]
        task = Task("T-ab-s", "ab", "Strategy report")
        result = agent.handle(task, {"payload": {"action": "strategy_report"}})
        assert result["status"] == "strategy_report"
        assert "strategy_count" in result

    def test_relay_signal(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["ab"]
        task = Task("T-ab-r", "ab", "Relay signal")
        result = agent.handle(task, {"payload": {
            "action": "relay_signal",
            "signal_type": "buy",
            "source_strategy": "momentum",
            "confidence": 0.9,
            "asset": "BTC",
        }})
        assert "connected" in result
        assert result["_callsign"] == "VAULT"


class TestNexusAgent:
    def test_default_status(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["sa"]
        task = Task("T-sa", "sa", "Agency status")
        result = agent.handle(task, {"payload": {}})
        assert result["status"] == "agency_status"
        assert "connected" in result
        assert "capabilities" in result
        assert result["_callsign"] == "NEXUS"

    def test_dispatch(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["sa"]
        task = Task("T-sa-d", "sa", "Dispatch workflow")
        result = agent.handle(task, {"payload": {
            "action": "dispatch",
            "workflow_id": "wf-test-1",
            "target_agents": ["agent_x"],
            "priority": "high",
        }})
        assert "connected" in result
        assert result["_callsign"] == "NEXUS"

    def test_check_workflow(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["sa"]
        task = Task("T-sa-w", "sa", "Check workflow")
        result = agent.handle(task, {"payload": {
            "action": "check_workflow",
            "workflow_id": "wf-42",
        }})
        assert result["status"] == "workflow_checked"
        assert result["workflow_id"] == "wf-42"

    def test_rbac_check(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task

        agent = EXPANSION_STUBS["sa"]
        task = Task("T-sa-r", "sa", "RBAC check")
        result = agent.handle(task, {"payload": {
            "action": "rbac_check",
            "agent_codename": "mc",
            "rbac_action": "dispatch",
        }})
        assert result["status"] == "rbac_checked"
        assert "allowed" in result


# ── Roster Integration Tests ──────────────────────────────────


class TestTriadRoster:
    def test_sentinel_in_roster(self):
        from ncl_agency_runtime.fpc.agents import get_agent

        agent = get_agent("nc")
        assert agent is not None
        assert agent.callsign == "SENTINEL"
        assert agent.name == "NCC Doctrine Enforcer"

    def test_vault_in_roster(self):
        from ncl_agency_runtime.fpc.agents import get_agent

        agent = get_agent("ab")
        assert agent is not None
        assert agent.callsign == "VAULT"
        assert agent.name == "AAC Asset Bridge"

    def test_nexus_in_roster(self):
        from ncl_agency_runtime.fpc.agents import get_agent

        agent = get_agent("sa")
        assert agent is not None
        assert agent.callsign == "NEXUS"
        assert agent.name == "BRS Orchestrator"

    def test_sentinel_by_callsign(self):
        from ncl_agency_runtime.fpc.agents import get_agent_by_callsign

        agent = get_agent_by_callsign("SENTINEL")
        assert agent is not None
        assert agent.codename == "nc"

    def test_vault_by_callsign(self):
        from ncl_agency_runtime.fpc.agents import get_agent_by_callsign

        agent = get_agent_by_callsign("VAULT")
        assert agent is not None
        assert agent.codename == "ab"

    def test_nexus_by_callsign(self):
        from ncl_agency_runtime.fpc.agents import get_agent_by_callsign

        agent = get_agent_by_callsign("NEXUS")
        assert agent is not None
        assert agent.codename == "sa"

    def test_triad_agents_have_missions(self):
        from ncl_agency_runtime.fpc.agents import get_agent

        for code in ["nc", "ab", "sa"]:
            agent = get_agent(code)
            assert agent is not None
            assert agent.mission, f"Agent {code} missing mission"

    def test_triad_agents_have_langgraph_nodes(self):
        from ncl_agency_runtime.fpc.agents import get_agent

        for code in ["nc", "ab", "sa"]:
            agent = get_agent(code)
            assert agent is not None
            assert len(agent.langgraph_nodes) > 0, f"Agent {code} missing LangGraph nodes"

    def test_triad_agents_have_capabilities(self):
        from ncl_agency_runtime.fpc.agents import get_agent

        for code in ["nc", "ab", "sa"]:
            agent = get_agent(code)
            assert agent is not None
            assert len(agent.capabilities) >= 3, f"Agent {code} needs more capabilities"

    def test_callsign_map_includes_triad(self):
        from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP

        assert CALLSIGN_MAP["nc"] == "SENTINEL"
        assert CALLSIGN_MAP["ab"] == "VAULT"
        assert CALLSIGN_MAP["sa"] == "NEXUS"

    def test_total_agent_count(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS

        assert len(ALL_AGENTS) == 31

    def test_expansion_count(self):
        from ncl_agency_runtime.fpc.agents import AgentTier, list_agents

        expansion = list_agents(AgentTier.EXPANSION)
        assert len(expansion) == 21
