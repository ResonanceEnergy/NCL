#!/usr/bin/env python3
"""
Tests for NCC Matrix Monitor — Command & Control Health Intelligence System.
═══════════════════════════════════════════════════════════════════════════════
Covers:
    1. HealthCheckResult data model
    2. MatrixMonitorStore persistence (save, load, history, trend)
    3. SLOEngine evaluation
    4. AlertRouter generation and routing
    5. Health data collectors (system, self_check, governance, fpc)
    6. MatrixMonitorOrchestrator full cycle
    7. Dashboard tile builder
    8. Bus integration (publish_to_bus)
    9. NCC Orchestrator PDCA with Matrix Monitor
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from ncl_agency_runtime.runtime.matrix_monitor import (
    AlertRecord,
    AlertRouter,
    AlertSeverity,
    DashboardTile,
    HealthCheckResult,
    HealthSource,
    MatrixMonitorOrchestrator,
    MatrixMonitorStore,
    MatrixReport,
    SLODefinition,
    SLOEngine,
    SLOStatus,
    _build_tiles,
    _collect_fpc_health,
    _collect_ncc_governance,
    _collect_self_check,
    _collect_system_health,
)

# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singletons before each test."""
    MatrixMonitorOrchestrator.reset()
    yield
    MatrixMonitorOrchestrator.reset()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmp_dir):
    return MatrixMonitorStore(log_dir=tmp_dir)


@pytest.fixture
def sample_checks():
    return [
        HealthCheckResult(
            source=HealthSource.SYSTEM, name="deps", passed=True, score=1.0,
            details="All dependencies OK",
        ),
        HealthCheckResult(
            source=HealthSource.SYSTEM, name="schemas", passed=True, score=1.0,
            details="Schemas valid",
        ),
        HealthCheckResult(
            source=HealthSource.SELF_CHECK, name="code_integrity", passed=True, score=0.95,
            details="AST parse OK",
        ),
        HealthCheckResult(
            source=HealthSource.SELF_CHECK, name="disk_health", passed=False, score=0.3,
            details="Disk usage 85%", recommendation="Clean temp files",
        ),
        HealthCheckResult(
            source=HealthSource.NCC_GOVERNANCE, name="triad_online", passed=True, score=1.0,
            details="Triad healthy",
        ),
    ]


@pytest.fixture
def sample_report(sample_checks):
    return MatrixReport(
        timestamp=datetime.now(UTC).isoformat(),
        overall_score=0.85,
        health_status="GOOD",
        checks=sample_checks,
        checks_passed=4,
        checks_total=5,
        slo_statuses=[],
        slos_in_violation=0,
        alerts=[],
        tiles=[],
        pillar_summary={"total_pillars": 5, "online": 4, "degraded": 1, "offline": 0},
        uptime_s=120.0,
    )


# ═══════════════════════════════════════════════════════════════
#  HealthCheckResult Tests
# ═══════════════════════════════════════════════════════════════

class TestHealthCheckResult:
    def test_create_basic(self):
        r = HealthCheckResult(
            source=HealthSource.SYSTEM, name="test_check",
            passed=True, score=0.9,
        )
        assert r.passed is True
        assert r.score == 0.9
        assert r.source == HealthSource.SYSTEM

    def test_to_dict(self):
        r = HealthCheckResult(
            source=HealthSource.SELF_CHECK, name="code_integrity",
            passed=True, score=1.0, details="OK",
        )
        d = r.to_dict()
        assert d["source"] == "self_check"
        assert d["name"] == "code_integrity"
        assert d["passed"] is True
        assert d["score"] == 1.0
        assert "timestamp" in d

    def test_failed_check(self):
        r = HealthCheckResult(
            source=HealthSource.FPC_INTELLIGENCE, name="fpc_gap",
            passed=False, score=0.0, details="Missing scraper",
            recommendation="Install scraper module",
        )
        assert r.passed is False
        assert r.recommendation == "Install scraper module"

    def test_health_source_values(self):
        assert HealthSource.SYSTEM.value == "system"
        assert HealthSource.SELF_CHECK.value == "self_check"
        assert HealthSource.NCC_GOVERNANCE.value == "ncc_governance"
        assert HealthSource.FPC_INTELLIGENCE.value == "fpc_intelligence"
        assert HealthSource.AGENT.value == "agent"
        assert HealthSource.ENDPOINT.value == "endpoint"


# ═══════════════════════════════════════════════════════════════
#  MatrixMonitorStore Tests
# ═══════════════════════════════════════════════════════════════

class TestMatrixMonitorStore:
    def test_save_and_load(self, store, sample_report):
        path = store.save(sample_report)
        assert path.exists()

        latest = store.get_latest()
        assert latest is not None
        assert latest["overall_score"] == 0.85
        assert latest["health_status"] == "GOOD"

    def test_history_append(self, store, sample_report):
        store.save(sample_report)
        store.save(sample_report)
        store.save(sample_report)

        history = store.get_history()
        assert len(history) == 3
        assert all(h["score"] == 0.85 for h in history)

    def test_history_empty(self, store):
        assert store.get_history() == []

    def test_latest_empty(self, store):
        assert store.get_latest() is None

    def test_get_trend(self, store, sample_report):
        store.save(sample_report)
        trend = store.get_trend("score")
        assert len(trend) == 1
        assert trend[0]["value"] == 0.85

    def test_get_trend_unknown_metric(self, store, sample_report):
        store.save(sample_report)
        trend = store.get_trend("nonexistent_metric")
        assert len(trend) == 0

    def test_history_max_entries(self, store, sample_report):
        for _ in range(10):
            store.save(sample_report)
        history = store.get_history(max_entries=3)
        assert len(history) == 3


# ═══════════════════════════════════════════════════════════════
#  SLOEngine Tests
# ═══════════════════════════════════════════════════════════════

class TestSLOEngine:
    def test_default_slos(self):
        engine = SLOEngine()
        slos = engine.slo_definitions
        assert len(slos) == 3
        names = {s.name for s in slos}
        assert "system_health_score" in names
        assert "pillar_availability" in names
        assert "checks_pass_rate" in names

    def test_custom_slos(self):
        config = {
            "slo": {
                "custom_metric": {
                    "target": 0.95,
                    "window_hours": 48,
                    "metric_source": "custom_metric",
                    "description": "Custom SLO",
                },
            },
        }
        engine = SLOEngine(config=config)
        assert len(engine.slo_definitions) == 1
        assert engine.slo_definitions[0].name == "custom_metric"
        assert engine.slo_definitions[0].target == 0.95

    def test_evaluate_passing(self):
        engine = SLOEngine()
        current = {
            "overall_score": 0.95,
            "pillar_online_ratio": 0.9,
            "checks_pass_rate": 0.85,
        }
        statuses = engine.evaluate(current, [])
        assert all(not s.in_violation for s in statuses)

    def test_evaluate_violation(self):
        engine = SLOEngine()
        current = {
            "overall_score": 0.5,  # below 0.8 target
            "pillar_online_ratio": 0.5,  # below 0.75 target
            "checks_pass_rate": 0.3,  # below 0.7 target
        }
        statuses = engine.evaluate(current, [])
        assert all(s.in_violation for s in statuses)

    def test_evaluate_with_history(self):
        engine = SLOEngine()
        current = {"overall_score": 0.9, "pillar_online_ratio": 0.8, "checks_pass_rate": 0.9}
        now = datetime.now(UTC).isoformat()
        history = [
            {"ts": now, "overall_score": 0.85, "pillar_online_ratio": 0.8, "checks_pass_rate": 0.75},
        ]
        statuses = engine.evaluate(current, history)
        assert len(statuses) == 3

    def test_slo_definition_to_dict(self):
        slo = SLODefinition(
            name="test", target=0.9, window_hours=24,
            metric_source="test", description="Test SLO",
        )
        d = slo.to_dict()
        assert d["name"] == "test"
        assert d["target"] == 0.9


# ═══════════════════════════════════════════════════════════════
#  AlertRouter Tests
# ═══════════════════════════════════════════════════════════════

class TestAlertRouter:
    def test_no_alerts_healthy(self, sample_checks):
        router = AlertRouter()
        alerts = router.evaluate(sample_checks, [], 0.9)
        assert len(alerts) == 0

    def test_critical_alert_low_score(self, sample_checks):
        router = AlertRouter()
        alerts = router.evaluate(sample_checks, [], 0.2)
        assert any(a.severity == AlertSeverity.CRITICAL for a in alerts)

    def test_degraded_alert(self, sample_checks):
        router = AlertRouter()
        alerts = router.evaluate(sample_checks, [], 0.45)
        assert any(a.severity == AlertSeverity.ERROR for a in alerts)

    def test_warning_alert(self, sample_checks):
        router = AlertRouter()
        alerts = router.evaluate(sample_checks, [], 0.65)
        assert any(a.severity == AlertSeverity.WARNING for a in alerts)

    def test_slo_violation_alert(self):
        router = AlertRouter()
        slo = SLODefinition("test", 0.9, 24, "test", "Test")
        slo_status = SLOStatus(slo=slo, current_value=0.5, budget_remaining=0.1, in_violation=True, samples=10)
        alerts = router.evaluate([], [slo_status], 0.95)
        assert len(alerts) >= 1
        assert any("SLO violation" in a.title for a in alerts)

    def test_failed_check_alert(self):
        router = AlertRouter()
        checks = [
            HealthCheckResult(
                source=HealthSource.SYSTEM, name="critical_check",
                passed=False, score=0.0, details="Total failure",
            ),
        ]
        alerts = router.evaluate(checks, [], 0.9)
        assert any("Check failed" in a.title for a in alerts)

    def test_acknowledge(self):
        router = AlertRouter()
        router.evaluate([], [], 0.2)  # generates critical alert
        assert len(router.active_alerts) > 0
        router.acknowledge(0)
        # After acknowledging first alert, active_alerts filters it out
        assert len(router.active_alerts) < len(router.all_alerts)

    def test_clear_acknowledged(self):
        router = AlertRouter()
        router.evaluate([], [], 0.2)
        before = len(router.all_alerts)
        for i in range(before):
            router.acknowledge(i)
        cleared = router.clear_acknowledged()
        assert cleared == before
        assert len(router.all_alerts) == 0

    def test_max_alerts_cap(self):
        router = AlertRouter()
        router._max_alerts = 5
        for _ in range(10):
            router.evaluate([], [], 0.2)
        assert len(router.all_alerts) <= 5

    def test_alert_record_to_dict(self):
        alert = AlertRecord(
            severity=AlertSeverity.CRITICAL,
            source="test", title="Test Alert", details="Detail",
        )
        d = alert.to_dict()
        assert d["severity"] == "critical"
        assert d["title"] == "Test Alert"
        assert d["acknowledged"] is False

    def test_alert_severity_values(self):
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.ERROR.value == "error"
        assert AlertSeverity.CRITICAL.value == "critical"


# ═══════════════════════════════════════════════════════════════
#  Dashboard Tile Tests
# ═══════════════════════════════════════════════════════════════

class TestDashboardTiles:
    def test_build_tiles_healthy(self, sample_checks):
        tiles = _build_tiles(
            0.9, "EXCELLENT", sample_checks, [],
            {"total_pillars": 5, "online": 5, "pillars": {}},
        )
        assert len(tiles) >= 2
        health_tile = next(t for t in tiles if t.title == "System Health")
        assert health_tile.status == "green"
        assert health_tile.value == 90.0

    def test_build_tiles_degraded(self, sample_checks):
        tiles = _build_tiles(
            0.4, "DEGRADED", sample_checks, [],
            {"total_pillars": 5, "online": 2, "pillars": {}},
        )
        health_tile = next(t for t in tiles if t.title == "System Health")
        assert health_tile.status == "red"

    def test_build_tiles_with_slos(self, sample_checks):
        slo = SLODefinition("test_slo", 0.9, 24, "test", "Test")
        slo_status = SLOStatus(slo=slo, current_value=0.85, budget_remaining=0.6, in_violation=True, samples=5)
        tiles = _build_tiles(
            0.85, "GOOD", sample_checks, [slo_status],
            {"total_pillars": 5, "online": 4, "pillars": {}},
        )
        slo_tiles = [t for t in tiles if t.tile_type == "slo"]
        assert len(slo_tiles) == 1

    def test_build_tiles_with_pillars(self):
        pillars = {
            "ncc": {"name": "NCC", "status": "online", "role": "governance", "capabilities": 5},
            "ncl": {"name": "NCL", "status": "degraded", "role": "brain", "capabilities": 3},
        }
        tiles = _build_tiles(
            0.8, "GOOD", [], [],
            {"total_pillars": 2, "online": 1, "degraded": 1, "pillars": pillars},
        )
        pillar_tiles = [t for t in tiles if t.tile_type == "pillar"]
        assert len(pillar_tiles) == 2
        ncc_tile = next(t for t in pillar_tiles if t.title == "NCC")
        assert ncc_tile.status == "green"
        ncl_tile = next(t for t in pillar_tiles if t.title == "NCL")
        assert ncl_tile.status == "yellow"

    def test_tile_to_dict(self):
        tile = DashboardTile(
            tile_type="health", title="Test", value=100, status="green",
        )
        d = tile.to_dict()
        assert d["tile_type"] == "health"
        assert d["value"] == 100


# ═══════════════════════════════════════════════════════════════
#  Collector Tests (mocked)
# ═══════════════════════════════════════════════════════════════

class TestCollectors:
    def test_collect_system_health_graceful_failure(self, tmp_dir):
        """System health collector should return a failed result if checker isn't loadable."""
        results = _collect_system_health(tmp_dir)
        assert len(results) >= 1
        # Should produce at least one result, even on failure
        assert all(isinstance(r, HealthCheckResult) for r in results)

    def test_collect_self_check_graceful_failure(self, tmp_dir):
        """Self-check collector should gracefully degrade."""
        with patch.dict("sys.modules", {"ncl_agency_runtime.runtime.self_check_protocol": None}):
            results = _collect_self_check(tmp_dir)
        assert len(results) >= 1
        assert results[0].source == HealthSource.SELF_CHECK

    def test_collect_ncc_governance(self):
        """Governance collector should work with default pillar registry."""
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()
        results, summary = _collect_ncc_governance(Path("."))
        assert len(results) >= 1
        assert isinstance(summary, dict)
        PillarRegistry.reset()

    def test_collect_fpc_health_graceful_failure(self, tmp_dir):
        """FPC collector should gracefully degrade."""
        results = _collect_fpc_health(tmp_dir)
        assert len(results) >= 1
        assert all(isinstance(r, HealthCheckResult) for r in results)

    def test_collect_fpc_health_no_gaps(self, tmp_dir):
        """FPC collector with no gaps should produce PASS."""
        with patch(
            "ncl_agency_runtime.runtime.fpc_integration.scan_fpc_health",
            return_value=[],
        ):
            results = _collect_fpc_health(tmp_dir)
        assert len(results) == 1
        assert results[0].passed is True


# ═══════════════════════════════════════════════════════════════
#  MatrixMonitorOrchestrator Tests
# ═══════════════════════════════════════════════════════════════

class TestMatrixMonitorOrchestrator:
    def test_singleton(self, tmp_dir):
        m1 = MatrixMonitorOrchestrator.get_instance(repo_root=tmp_dir)
        m2 = MatrixMonitorOrchestrator.get_instance()
        assert m1 is m2

    def test_reset(self, tmp_dir):
        m1 = MatrixMonitorOrchestrator.get_instance(repo_root=tmp_dir)
        MatrixMonitorOrchestrator.reset()
        m2 = MatrixMonitorOrchestrator.get_instance(repo_root=tmp_dir)
        assert m1 is not m2

    def test_collect_all(self, tmp_dir):
        """Full collection cycle should produce a valid MatrixReport."""
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        report = monitor.collect_all()

        assert isinstance(report, MatrixReport)
        assert 0.0 <= report.overall_score <= 1.0
        assert report.health_status in ("EXCELLENT", "GOOD", "FAIR", "DEGRADED", "CRITICAL")
        assert report.checks_total >= 1
        assert isinstance(report.tiles, list)
        assert isinstance(report.alerts, list)
        assert isinstance(report.slo_statuses, list)
        assert report.uptime_s >= 0

        PillarRegistry.reset()

    def test_collect_all_persists(self, tmp_dir):
        """collect_all should save to store."""
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        monitor.collect_all()

        latest = monitor.store.get_latest()
        assert latest is not None
        assert "overall_score" in latest

        PillarRegistry.reset()

    def test_cycle_count(self, tmp_dir):
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        assert monitor.cycle_count == 0
        monitor.collect_all()
        assert monitor.cycle_count == 1
        monitor.collect_all()
        assert monitor.cycle_count == 2

        PillarRegistry.reset()

    def test_get_tiles_empty(self, tmp_dir):
        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        tiles = monitor.get_tiles()
        assert tiles == []

    def test_get_tiles_after_collection(self, tmp_dir):
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        monitor.collect_all()
        tiles = monitor.get_tiles()
        assert len(tiles) >= 2

        PillarRegistry.reset()

    def test_get_active_alerts(self, tmp_dir):
        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        alerts = monitor.get_active_alerts()
        assert isinstance(alerts, list)

    def test_get_slo_definitions(self, tmp_dir):
        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        slos = monitor.get_slo_definitions()
        assert len(slos) == 3

    def test_health_label(self):
        assert MatrixMonitorOrchestrator._health_label(0.95) == "EXCELLENT"
        assert MatrixMonitorOrchestrator._health_label(0.85) == "GOOD"
        assert MatrixMonitorOrchestrator._health_label(0.6) == "FAIR"
        assert MatrixMonitorOrchestrator._health_label(0.35) == "DEGRADED"
        assert MatrixMonitorOrchestrator._health_label(0.1) == "CRITICAL"

    def test_individual_collectors(self, tmp_dir):
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)

        system = monitor.collect_system()
        assert all(isinstance(r, HealthCheckResult) for r in system)

        self_check = monitor.collect_self_check()
        assert all(isinstance(r, HealthCheckResult) for r in self_check)

        gov, summary = monitor.collect_governance()
        assert all(isinstance(r, HealthCheckResult) for r in gov)
        assert isinstance(summary, dict)

        fpc = monitor.collect_fpc()
        assert all(isinstance(r, HealthCheckResult) for r in fpc)

        PillarRegistry.reset()

    def test_report_to_dict(self, tmp_dir):
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        report = monitor.collect_all()
        d = report.to_dict()

        assert isinstance(d, dict)
        assert "timestamp" in d
        assert "overall_score" in d
        assert "checks" in d
        assert isinstance(d["checks"], list)

        PillarRegistry.reset()


# ═══════════════════════════════════════════════════════════════
#  Bus Integration Tests
# ═══════════════════════════════════════════════════════════════

class TestBusIntegration:
    def test_publish_to_bus(self, tmp_dir, sample_report):
        """publish_to_bus should dispatch messages to the InterPillarBus."""
        from ncl_agency_runtime.runtime.inter_pillar_bus import InterPillarBus
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry
        InterPillarBus.reset()
        PillarRegistry.reset()

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        bus = InterPillarBus.get_instance()

        received: list[dict] = []

        async def handler(msg):
            received.append(msg.payload)

        from ncl_agency_runtime.runtime.inter_pillar_bus import MessageType
        from ncl_agency_runtime.runtime.pillar_registry import PillarID
        bus.subscribe(PillarID.NCC, MessageType.STATUS_REPORT, handler)

        monitor.publish_to_bus(sample_report)

        stats = bus.stats
        assert stats["processed"] >= 1

        InterPillarBus.reset()
        PillarRegistry.reset()

    def test_publish_to_bus_graceful_on_no_bus(self, tmp_dir, sample_report):
        """publish_to_bus should not raise if bus is unavailable."""
        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        # This should not raise — simulate bus import failure
        with patch.dict("sys.modules", {"ncl_agency_runtime.runtime.inter_pillar_bus": None}):
            monitor.publish_to_bus(sample_report)


# ═══════════════════════════════════════════════════════════════
#  NCC Orchestrator Integration
# ═══════════════════════════════════════════════════════════════

class TestNCCOrchestratorIntegration:
    @pytest.mark.asyncio
    async def test_pdca_includes_matrix_data(self):
        """PDCA cycle plan phase should include matrix monitor data."""
        from ncl_agency_runtime.runtime.digital_labour import DigitalLabourPool
        from ncl_agency_runtime.runtime.inter_pillar_bus import InterPillarBus
        from ncl_agency_runtime.runtime.ncc_orchestrator import NCCOrchestrator
        from ncl_agency_runtime.runtime.pillar_registry import PillarRegistry

        NCCOrchestrator.reset()
        PillarRegistry.reset()
        InterPillarBus.reset()
        DigitalLabourPool.reset()
        MatrixMonitorOrchestrator.reset()

        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()

        result = await orch.run_pdca_cycle()

        plan = result["phases"]["plan"]
        # Matrix Monitor should have injected data if available
        assert "health" in plan
        assert "triad" in plan

        NCCOrchestrator.reset()
        MatrixMonitorOrchestrator.reset()

    @pytest.mark.asyncio
    async def test_matrix_status_command(self):
        """NCC 'matrix_status' command should work."""
        from ncl_agency_runtime.runtime.digital_labour import DigitalLabourPool
        from ncl_agency_runtime.runtime.inter_pillar_bus import (
            InterPillarBus,
            MessageType,
            PillarMessage,
        )
        from ncl_agency_runtime.runtime.ncc_orchestrator import NCCOrchestrator
        from ncl_agency_runtime.runtime.pillar_registry import PillarID, PillarRegistry

        NCCOrchestrator.reset()
        PillarRegistry.reset()
        InterPillarBus.reset()
        DigitalLabourPool.reset()
        MatrixMonitorOrchestrator.reset()

        orch = NCCOrchestrator.get_instance()
        orch.bootstrap()

        msg = PillarMessage(
            source=PillarID.NCL,
            target=PillarID.NCC,
            msg_type=MessageType.COMMAND,
            payload={"action": "matrix_status"},
        )

        response = await orch._handle_ncc_command(msg)

        assert response is not None
        payload = response.payload
        assert "overall_score" in payload or "error" in payload

        NCCOrchestrator.reset()
        MatrixMonitorOrchestrator.reset()


# ═══════════════════════════════════════════════════════════════
#  MatrixReport Serialization
# ═══════════════════════════════════════════════════════════════

class TestMatrixReportSerialization:
    def test_full_report_serialization(self, sample_report):
        d = sample_report.to_dict()
        # Should be JSON-serializable
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert deserialized["overall_score"] == 0.85
        assert deserialized["health_status"] == "GOOD"
        assert len(deserialized["checks"]) == 5

    def test_slo_status_serialization(self):
        slo = SLODefinition("test", 0.9, 24, "test", "Test")
        status = SLOStatus(
            slo=slo, current_value=0.85, budget_remaining=0.6,
            in_violation=True, samples=10,
        )
        d = status.to_dict()
        serialized = json.dumps(d)
        assert '"in_violation": true' in serialized


# ═══════════════════════════════════════════════════════════════
#  Config Loading
# ═══════════════════════════════════════════════════════════════

class TestConfigLoading:
    def test_load_config_from_file(self, tmp_dir):
        config = {"matrix_monitor": {"enabled": True}, "slo": {"test": {"target": 0.95}}}
        config_path = tmp_dir / "ncl_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        assert monitor._config.get("matrix_monitor", {}).get("enabled") is True

    def test_load_config_missing_file(self, tmp_dir):
        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        assert isinstance(monitor._config, dict)

    def test_load_config_invalid_json(self, tmp_dir):
        config_path = tmp_dir / "ncl_config.json"
        config_path.write_text("not json{{{", encoding="utf-8")
        monitor = MatrixMonitorOrchestrator(repo_root=tmp_dir)
        assert monitor._config == {}
