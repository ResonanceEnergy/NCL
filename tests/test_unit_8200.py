"""Tests for the Unit 8200 Intelligence Doctrine integration.

Covers:
  - IntelligenceDiscipline and ClassificationLevel enums
  - CollectionPipeline TCPED cycle
  - FusionCenter multi-source correlation and anomaly detection
  - RedTeamEngine probes, findings, defenses, zero-day scan, stress test
  - CompartmentalizationMatrix access control and clearances
  - ThreatMatrix CIOV risk assessment
  - OperationalCell (Matzov) lifecycle
  - OODALoop decision cycle
  - Unit8200Doctrine unified engine
  - CipherAgent and AegisAgent handle() integration
  - Roster integration (26 agents, 16 expansion, callsign map)
  - Unit 8200 EventTypes
"""

from __future__ import annotations

# ── Intelligence Discipline Tests ──────────────────────────────

class TestIntelligenceDisciplines:

    def test_all_disciplines_exist(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import IntelligenceDiscipline
        assert IntelligenceDiscipline.SIGINT == "sigint"
        assert IntelligenceDiscipline.COMINT == "comint"
        assert IntelligenceDiscipline.ELINT == "elint"
        assert IntelligenceDiscipline.CYBINT == "cybint"
        assert IntelligenceDiscipline.OSINT == "osint"
        assert IntelligenceDiscipline.HUMINT == "humint"

    def test_discipline_count(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import IntelligenceDiscipline
        assert len(IntelligenceDiscipline) == 6

    def test_classification_levels(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ClassificationLevel
        levels = list(ClassificationLevel)
        assert len(levels) == 5
        assert ClassificationLevel.UNCLASSIFIED.value == "unclassified"
        assert ClassificationLevel.COMPARTMENTED.value == "compartmented"

    def test_threat_categories(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatCategory
        assert len(ThreatCategory) == 6
        assert ThreatCategory.ADVERSARIAL.value == "adversarial"
        assert ThreatCategory.MODEL_DRIFT.value == "model_drift"


# ── Collection Pipeline Tests ──────────────────────────────────

class TestCollectionPipeline:

    def test_task_collection(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
        )
        pipeline = CollectionPipeline()
        tasking = pipeline.task_collection(
            IntelligenceDiscipline.SIGINT,
            {"target": "telemetry_stream"},
            "high",
        )
        assert tasking["status"] == "tasked"
        assert tasking["discipline"] == "sigint"
        assert tasking["priority"] == "high"
        assert tasking["task_id"] in pipeline.collection_plan

    def test_collect_raw_data(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
        )
        pipeline = CollectionPipeline()
        take = pipeline.collect(
            IntelligenceDiscipline.OSINT,
            {"market_signal": True, "value": 42},
            "market_feed",
        )
        assert take["status"] == "collected"
        assert take["discipline"] == "osint"
        assert len(pipeline.raw_takes) == 1

    def test_process_raw_take(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
        )
        pipeline = CollectionPipeline()
        take = pipeline.collect(
            IntelligenceDiscipline.CYBINT,
            {"threat_indicator": True},
            "system",
        )
        report = pipeline.process(take)
        assert report.discipline == IntelligenceDiscipline.CYBINT
        assert report.source == "system"
        assert report.confidence > 0.0
        assert len(report.fingerprint) == 16

    def test_process_pii_content_classified_top_secret(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            ClassificationLevel,
            CollectionPipeline,
            IntelligenceDiscipline,
        )
        pipeline = CollectionPipeline()
        take = pipeline.collect(
            IntelligenceDiscipline.HUMINT,
            {"pii": True, "name": "test"},
            "user_input",
        )
        report = pipeline.process(take)
        assert report.classification == ClassificationLevel.TOP_SECRET

    def test_exploit_sigint_anomaly(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
            IntelligenceReport,
        )
        pipeline = CollectionPipeline()
        report = IntelligenceReport(
            discipline=IntelligenceDiscipline.SIGINT,
            source="telemetry",
            content={"anomaly_detected": True},
        )
        result = pipeline.exploit(report)
        assert result["exploited"] is True
        assert "signal_anomaly" in result["indicators"]
        assert "investigate_signal_source" in result["recommended_actions"]

    def test_exploit_osint_market_signal(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
            IntelligenceReport,
        )
        pipeline = CollectionPipeline()
        report = IntelligenceReport(
            discipline=IntelligenceDiscipline.OSINT,
            source="feed",
            content={"market_signal": True},
        )
        result = pipeline.exploit(report)
        assert "market_movement" in result["indicators"]

    def test_disseminate(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceReport,
        )
        pipeline = CollectionPipeline()
        report = IntelligenceReport(source="test")
        result = pipeline.disseminate(report, ["mc", "so"])
        assert result["recipients"] == ["mc", "so"]
        assert report.dissemination_list == ["mc", "so"]

    def test_full_cycle(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
        )
        pipeline = CollectionPipeline()
        result = pipeline.run_full_cycle(
            IntelligenceDiscipline.ELINT,
            {"signal_strength": 0.9},
            "radar_system",
            ["mc", "dx"],
        )
        assert result["cycle_complete"] is True
        assert result["discipline"] == "elint"
        assert result["confidence"] > 0.0
        assert len(pipeline.processed) == 1

    def test_source_reliability_boosted_for_system(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            CollectionPipeline,
            IntelligenceDiscipline,
        )
        pipeline = CollectionPipeline()
        take = pipeline.collect(
            IntelligenceDiscipline.SIGINT,
            {"data": "test"},
            "system",
        )
        report = pipeline.process(take)
        # System source should get a boost
        assert report.confidence >= 0.85


# ── Fusion Center Tests ────────────────────────────────────────

class TestFusionCenter:

    def test_ingest_report(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            FusionCenter,
            IntelligenceDiscipline,
            IntelligenceReport,
        )
        fusion = FusionCenter()
        report = IntelligenceReport(
            discipline=IntelligenceDiscipline.SIGINT,
            source="test",
            content={"key": "value"},
        )
        fusion.ingest(report)
        assert fusion.total_reports == 1
        assert "sigint" in fusion.active_disciplines

    def test_correlate_cross_discipline(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            FusionCenter,
            IntelligenceDiscipline,
            IntelligenceReport,
        )
        fusion = FusionCenter()
        # Two reports from different disciplines with overlapping content
        r1 = IntelligenceReport(
            discipline=IntelligenceDiscipline.SIGINT,
            source="sigint_collector",
            content={"target": "alpha", "timestamp": 123},
        )
        r2 = IntelligenceReport(
            discipline=IntelligenceDiscipline.OSINT,
            source="osint_collector",
            content={"target": "alpha", "source_type": "public"},
        )
        fusion.ingest(r1)
        fusion.ingest(r2)
        correlations = fusion.correlate()
        assert len(correlations) >= 1
        assert correlations[0]["discipline_a"] != correlations[0]["discipline_b"]

    def test_detect_anomalies_collection_gap(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            FusionCenter,
            IntelligenceDiscipline,
            IntelligenceReport,
        )
        fusion = FusionCenter()
        # Only ingest SIGINT -- other disciplines are missing
        fusion.ingest(IntelligenceReport(
            discipline=IntelligenceDiscipline.SIGINT,
            content={"test": True},
        ))
        anomalies = fusion.detect_anomalies()
        gap_anomaly = [a for a in anomalies if a["type"] == "collection_gap"]
        assert len(gap_anomaly) == 1
        assert "osint" in gap_anomaly[0]["missing_disciplines"]

    def test_generate_picture_empty(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import FusionCenter
        fusion = FusionCenter()
        picture = fusion.generate_picture()
        assert picture["total_reports"] == 0
        assert picture["fusion_score"] == 0.0
        assert "DARK" in picture["operational_picture"]

    def test_generate_picture_with_data(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            FusionCenter,
            IntelligenceDiscipline,
            IntelligenceReport,
        )
        fusion = FusionCenter()
        for disc in [IntelligenceDiscipline.SIGINT, IntelligenceDiscipline.OSINT,
                     IntelligenceDiscipline.CYBINT]:
            fusion.ingest(IntelligenceReport(
                discipline=disc,
                source="test",
                content={"target": "bravo"},
                confidence=0.8,
            ))
        picture = fusion.generate_picture()
        assert picture["total_reports"] == 3
        assert set(picture["active_disciplines"]) == {"sigint", "osint", "cybint"}
        assert picture["fusion_score"] > 0.0

    def test_content_overlap(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import FusionCenter
        overlap = FusionCenter._content_overlap(
            {"a": 1, "b": 2},
            {"a": 1, "c": 3},
        )
        assert overlap > 0.0
        # Empty content should have 0 overlap
        assert FusionCenter._content_overlap({}, {"a": 1}) == 0.0


# ── Red Team Engine Tests ──────────────────────────────────────

class TestRedTeamEngine:

    def test_noise_injection_probe(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        probe = rt.probe("model_v1", "noise_injection", {
            "predictions": [100, 101, 99, 102, 98],
            "noise_level": 0.5,
        })
        assert probe.target == "model_v1"
        assert probe.method == "noise_injection"
        assert "vulnerability_detected" in probe.result
        assert len(rt.probes) == 1

    def test_drift_simulation_probe(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        probe = rt.probe("pipeline", "drift_simulation", {
            "drift_magnitude": 0.1,
            "detection_threshold": 0.15,
        })
        # drift < threshold = undetected = vulnerability
        assert probe.result["vulnerability_detected"] is True
        assert probe.result["vulnerability_type"] == "undetected_drift"

    def test_boundary_probe(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        probe = rt.probe("inputs", "boundary_probe", {
            "test_values": [0, 1e15, float("nan")],
        })
        assert probe.result["vulnerability_detected"] is True
        assert len(probe.result["failures"]) > 0

    def test_replay_attack_probe(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        probe = rt.probe("data_feed", "replay_attack", {
            "staleness_hours": 48,
            "max_age_hours": 12,
        })
        assert probe.result["vulnerability_detected"] is True
        assert probe.result["severity"] == "high"

    def test_assess_finding_creates_finding(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        probe = rt.probe("model", "noise_injection", {
            "predictions": [100, 101, 99],
            "noise_level": 5.0,  # Extreme noise
        })
        if probe.result.get("vulnerability_detected"):
            finding = rt.assess_finding(probe)
            assert finding is not None
            assert finding.target == "model"
            assert len(rt.findings) == 1

    def test_assess_finding_returns_none_if_clean(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        probe = rt.probe("model", "replay_attack", {
            "staleness_hours": 1,
            "max_age_hours": 12,
        })
        finding = rt.assess_finding(probe)
        assert finding is None

    def test_defend_noise(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        defense = rt.defend("noise", {})
        assert defense["action"] == "apply_robust_scaling"
        assert len(rt.defenses) == 1

    def test_defend_drift(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        defense = rt.defend("drift", {})
        assert defense["action"] == "trigger_retraining"

    def test_defend_unknown_threat(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        defense = rt.defend("alien_invasion", {})
        assert defense["action"] == "monitor"

    def test_zero_day_scan_clean(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        result = rt.zero_day_scan([100.0, 101.5, 99.2, 102.1, 98.8])
        assert result["status"] == "scanned"
        assert result["zero_day_clear"] is True
        assert result["severity"] == "clean"

    def test_zero_day_scan_constant_collapse(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        result = rt.zero_day_scan([42.0, 42.0, 42.0, 42.0, 42.0])
        assert "constant_prediction_collapse" in result["vulnerabilities"]
        assert result["zero_day_clear"] is False

    def test_zero_day_scan_nan_contamination(self):
        import math

        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        result = rt.zero_day_scan([100.0, float("nan"), 99.0, math.inf])
        assert any("nan_inf" in v for v in result["vulnerabilities"])

    def test_zero_day_scan_empty(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        result = rt.zero_day_scan([])
        assert result["status"] == "no_data"

    def test_stress_test(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        result = rt.stress_test([100.0, 101.0, 99.0, 102.0, 98.0])
        assert result["status"] == "stress_tested"
        assert result["levels_tested"] == 5
        assert result["levels_passed"] > 0

    def test_stress_test_empty(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        result = rt.stress_test([])
        assert result["status"] == "no_data"

    def test_summary(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import RedTeamEngine
        rt = RedTeamEngine()
        rt.probe("a", "noise_injection", {"predictions": [1, 2, 3], "noise_level": 0.1})
        rt.probe("b", "boundary_probe", {"test_values": [float("nan")]})
        summary = rt.summary()
        assert summary["total_probes"] == 2


# ── Compartmentalization Matrix Tests ──────────────────────────

class TestCompartmentalizationMatrix:

    def test_default_compartments(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        assert "FORECAST" in matrix.compartments
        assert "THREAT" in matrix.compartments
        assert "mc" in matrix.compartments["GOVERNANCE"]

    def test_check_access_granted(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        result = matrix.check_access("mc", "FORECAST")
        assert result["access"] is True
        assert result["reason"] == "authorized"

    def test_check_access_denied(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        result = matrix.check_access("dx", "FINANCIAL")
        assert result["access"] is False
        assert result["reason"] == "need-to-know denied"

    def test_check_access_nonexistent_compartment(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        result = matrix.check_access("mc", "NONEXISTENT")
        assert result["access"] is False
        assert "does not exist" in result["reason"]

    def test_create_compartment(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        matrix.create_compartment("SPECIAL_OPS", ["mc", "sg", "rd"])
        result = matrix.check_access("sg", "SPECIAL_OPS")
        assert result["access"] is True
        result2 = matrix.check_access("dx", "SPECIAL_OPS")
        assert result2["access"] is False

    def test_grant_and_check_clearance(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            ClassificationLevel,
            CompartmentalizationMatrix,
        )
        matrix = CompartmentalizationMatrix()
        matrix.grant_clearance("mc", ClassificationLevel.TOP_SECRET)
        assert matrix.check_clearance("mc", ClassificationLevel.SECRET) is True
        assert matrix.check_clearance("mc", ClassificationLevel.TOP_SECRET) is True

    def test_clearance_denied_insufficient_level(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            ClassificationLevel,
            CompartmentalizationMatrix,
        )
        matrix = CompartmentalizationMatrix()
        matrix.grant_clearance("dx", ClassificationLevel.CONFIDENTIAL)
        assert matrix.check_clearance("dx", ClassificationLevel.SECRET) is False

    def test_classify_report(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            ClassificationLevel,
            CompartmentalizationMatrix,
            IntelligenceReport,
        )
        matrix = CompartmentalizationMatrix()
        report = IntelligenceReport(source="test")
        classified = matrix.classify_report(report, "THREAT")
        assert classified.compartment == "THREAT"
        assert classified.classification == ClassificationLevel.COMPARTMENTED

    def test_access_log(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        matrix.check_access("mc", "FORECAST")
        matrix.check_access("dx", "FINANCIAL")
        assert len(matrix.access_log) == 2

    def test_summary(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import CompartmentalizationMatrix
        matrix = CompartmentalizationMatrix()
        matrix.check_access("mc", "FORECAST")
        matrix.check_access("dx", "FINANCIAL")
        s = matrix.summary()
        assert s["compartment_count"] == 5
        assert s["access_checks"] == 2
        assert s["denied_count"] == 1


# ── Threat Matrix Tests ────────────────────────────────────────

class TestThreatMatrix:

    def test_add_threat(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatCategory, ThreatMatrix
        tm = ThreatMatrix()
        threat = tm.add_threat(
            "T-100", ThreatCategory.ADVERSARIAL,
            "Test adversarial threat",
            capability=0.8, intent=0.7, opportunity=0.5, vulnerability=0.6,
        )
        assert threat.risk_score > 0.0
        assert len(tm.threats) == 1

    def test_ciov_geometric_mean(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatAssessment, ThreatCategory
        t = ThreatAssessment(
            threat_id="T-X", category=ThreatCategory.DATA_INTEGRITY,
            description="test",
            capability=0.5, intent=0.5, opportunity=0.5, vulnerability=0.5,
        )
        risk = t.compute_risk()
        assert risk == 0.5  # (0.5^4)^0.25 = 0.5

    def test_ciov_zero_factor(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatAssessment, ThreatCategory
        t = ThreatAssessment(
            threat_id="T-Y", category=ThreatCategory.INSIDER,
            description="test",
            capability=0.8, intent=0.0, opportunity=0.9, vulnerability=0.7,
        )
        risk = t.compute_risk()
        assert risk == 0.0  # Intent is 0 -> product is 0

    def test_prioritize(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatCategory, ThreatMatrix
        tm = ThreatMatrix()
        tm.add_threat("T-A", ThreatCategory.ADVERSARIAL, "Low risk",
                      capability=0.1, intent=0.1, opportunity=0.1, vulnerability=0.1)
        tm.add_threat("T-B", ThreatCategory.MODEL_DRIFT, "High risk",
                      capability=0.9, intent=0.9, opportunity=0.9, vulnerability=0.9)
        ranked = tm.prioritize()
        assert ranked[0].threat_id == "T-B"
        assert ranked[0].risk_score > ranked[1].risk_score

    def test_high_risk_threats(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatCategory, ThreatMatrix
        tm = ThreatMatrix()
        tm.add_threat("T-LOW", ThreatCategory.INFRASTRUCTURE, "Low",
                      capability=0.1, intent=0.1, opportunity=0.1, vulnerability=0.1)
        tm.add_threat("T-HIGH", ThreatCategory.ADVERSARIAL, "High",
                      capability=0.9, intent=0.9, opportunity=0.9, vulnerability=0.9)
        high = tm.high_risk_threats(threshold=0.5)
        assert len(high) == 1
        assert high[0].threat_id == "T-HIGH"

    def test_category_summary(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatCategory, ThreatMatrix
        tm = ThreatMatrix()
        tm.add_threat("T-1", ThreatCategory.ADVERSARIAL, "a")
        tm.add_threat("T-2", ThreatCategory.ADVERSARIAL, "b")
        tm.add_threat("T-3", ThreatCategory.MODEL_DRIFT, "c")
        cats = tm.category_summary()
        assert cats["adversarial"] == 2
        assert cats["model_drift"] == 1

    def test_summary(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import ThreatCategory, ThreatMatrix
        tm = ThreatMatrix()
        tm.add_threat("T-1", ThreatCategory.DATA_INTEGRITY, "test",
                      capability=0.5, intent=0.5, opportunity=0.5, vulnerability=0.5)
        s = tm.summary()
        assert s["total_threats"] == 1
        assert s["highest_risk"] > 0.0
        assert s["active_threats"] == 1


# ── Operational Cell Tests ─────────────────────────────────────

class TestOperationalCell:

    def test_create_cell(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-1", ["mc", "sg", "rd"], "Threat hunting")
        assert cell.state == "standby"
        assert len(cell.agents) == 3

    def test_activate_cell(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-2", ["mc", "so"], "Defense ops")
        status = cell.activate()
        assert status.state == "active"
        assert cell.state == "active"

    def test_brief_cell(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            IntelligenceDiscipline,
            IntelligenceReport,
            OperationalCell,
        )
        cell = OperationalCell("CELL-3", ["mc"], "Intel analysis")
        reports = [
            IntelligenceReport(discipline=IntelligenceDiscipline.SIGINT, compartment="THREAT"),
            IntelligenceReport(discipline=IntelligenceDiscipline.OSINT, compartment="THREAT"),
        ]
        result = cell.brief(reports)
        assert result["reports_received"] == 2
        assert cell.intel_briefed == 2

    def test_execute_task(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-4", ["sg"], "Collection")
        cell.activate()
        result = cell.execute_task("Collect SIGINT from channel A")
        assert result["success"] is True
        assert cell.tasks_completed == 1

    def test_execute_task_not_active(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-5", ["sg"], "Test")
        result = cell.execute_task("Should fail")
        assert result["success"] is False

    def test_debrief(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-6", ["mc", "sg"], "Fusion ops")
        cell.activate()
        cell.execute_task("Task 1")
        cell.execute_task("Task 2")
        debrief = cell.debrief()
        assert debrief["tasks_completed"] == 2
        assert debrief["success_rate"] == 1.0
        assert cell.state == "debriefing"

    def test_disband(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-7", ["rd"], "Red team")
        cell.activate()
        cell.disband()
        assert cell.state == "disbanded"

    def test_status(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OperationalCell
        cell = OperationalCell("CELL-8", ["mc", "sg", "rd"], "Multi-op")
        status = cell.status()
        assert status.cell_id == "CELL-8"
        assert status.state == "standby"
        assert len(status.agents) == 3


# ── OODA Loop Tests ────────────────────────────────────────────

class TestOODALoop:

    def test_observe(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        snap = ooda.observe(["anomaly in channel 3", "spike in telemetry"])
        assert snap.phase == "observe"
        assert len(snap.observations) == 2

    def test_orient(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        snap = ooda.orient(
            ["spike detected"],
            {"threat_level": "elevated", "confidence": 0.8},
        )
        assert snap.phase == "orient"
        assert snap.orientation["threat_level"] == "elevated"

    def test_decide(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        snap = ooda.decide(
            ["data point"],
            {"context": "test"},
            "activate_defense",
        )
        assert snap.phase == "decide"
        assert snap.decision == "activate_defense"

    def test_act(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        snap = ooda.act("deploy_patch", "patched_model_v2", cycle_time_ms=15.5)
        assert snap.phase == "act"
        assert snap.action_taken == "patched_model_v2"
        assert snap.cycle_time_ms == 15.5

    def test_full_cycle(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        result = ooda.full_cycle(
            observations=["drift detected in model A"],
            context={"threat_level": "high", "confidence": 0.9},
            decision="retrain_model",
            action="triggered_retraining_pipeline",
        )
        assert result["cycle_complete"] is True
        assert result["decision"] == "retrain_model"
        assert result["total_cycles"] == 1

    def test_cycle_stats(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        ooda.full_cycle(["obs1"], {"confidence": 0.5}, "act1", "action1")
        ooda.full_cycle(["obs2"], {"confidence": 0.7}, "act2", "action2")
        stats = ooda.cycle_stats()
        assert stats["total_cycles"] == 2
        assert stats["avg_cycle_ms"] >= 0.0

    def test_cycle_stats_empty(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import OODALoop
        ooda = OODALoop()
        stats = ooda.cycle_stats()
        assert stats["total_cycles"] == 0


# ── Unit 8200 Doctrine Engine Tests ────────────────────────────

class TestUnit8200Doctrine:

    def test_initialize(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        result = doctrine.initialize()
        assert result["status"] == "initialized"
        assert result["principles"] == 10
        assert result["threats_seeded"] == 5
        assert result["compartments"] == 5
        assert result["disciplines"] == 6
        assert doctrine._initialized is True

    def test_principles_count(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        assert len(Unit8200Doctrine.PRINCIPLES) == 10

    def test_score_doctrine_full_compliance(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        context = {
            "collection_active": True,
            "multi_source_fusion": True,
            "red_team_enabled": True,
            "compartments_enforced": True,
            "cells_formed": True,
            "zero_day_scanning": True,
            "flat_decisions": True,
            "ooda_fast": True,
            "persistence_collection": True,
            "precision_targeting": True,
        }
        score = doctrine.score_doctrine(context)
        assert score["score"] == 1.0
        assert score["grade"] == "S"
        assert len(score["principles_violated"]) == 0

    def test_score_doctrine_partial(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        context = {
            "collection_active": True,
            "red_team_enabled": True,
            "zero_day_scanning": True,
        }
        score = doctrine.score_doctrine(context)
        assert 0.0 < score["score"] < 1.0
        assert "collect_trust_nothing" in score["principles_met"]
        assert "fuse_before_analyze" in score["principles_violated"]

    def test_score_doctrine_empty(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        score = doctrine.score_doctrine({})
        assert score["score"] == 0.0
        assert score["grade"] == "F"

    def test_form_cell(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        cell = doctrine.form_cell("ALPHA", ["mc", "sg", "rd"], "Threat hunting")
        assert cell.cell_id == "ALPHA"
        assert "ALPHA" in doctrine.cells

    def test_run_intelligence_cycle(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            IntelligenceDiscipline,
            Unit8200Doctrine,
        )
        doctrine = Unit8200Doctrine()
        result = doctrine.run_intelligence_cycle(
            IntelligenceDiscipline.SIGINT,
            {"anomaly_detected": True},
            "agent.ds",
            ["mc"],
        )
        assert result["cycle_complete"] is True
        assert result["discipline"] == "sigint"
        # Should auto-ingest into fusion center
        assert doctrine.fusion.total_reports == 1

    def test_red_team_predictions(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        result = doctrine.red_team_predictions([100.0, 101.0, 99.5, 102.0, 98.5])
        assert "zero_day" in result
        assert "stress_test" in result
        assert "noise_probe" in result
        assert result["zero_day"]["status"] == "scanned"

    def test_operational_readiness_fresh(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        readiness = doctrine.operational_readiness()
        assert readiness["status"] == "NOT_READY"
        assert readiness["initialized"] is False

    def test_operational_readiness_initialized(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import Unit8200Doctrine
        doctrine = Unit8200Doctrine()
        doctrine.initialize()
        readiness = doctrine.operational_readiness()
        assert readiness["readiness_score"] > 0.0
        assert readiness["initialized"] is True
        assert readiness["components"]["threat_assessment"] is True

    def test_operational_readiness_full(self):
        from ncl_agency_runtime.fpc.unit_8200_doctrine import (
            IntelligenceDiscipline,
            Unit8200Doctrine,
        )
        doctrine = Unit8200Doctrine()
        doctrine.initialize()
        # Run collection + fusion
        doctrine.run_intelligence_cycle(
            IntelligenceDiscipline.SIGINT, {"data": 1}, "test",
        )
        # Run red team
        doctrine.red_team_predictions([100, 101, 99])
        # Form a cell
        doctrine.form_cell("C1", ["mc"], "test")
        # Run OODA
        doctrine.ooda.full_cycle(["obs"], {"confidence": 0.8}, "decide", "act")

        readiness = doctrine.operational_readiness()
        assert readiness["readiness_score"] >= 0.85
        assert readiness["status"] == "OPERATIONAL"


# ── Agent Integration Tests ────────────────────────────────────

class TestCipherAgent:

    def test_collect_intelligence(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-cipher-1", "sg", "Collect SIGINT")
        result = EXPANSION_STUBS["sg"].handle(task, {"payload": {
            "action": "collect",
            "discipline": "sigint",
            "raw_data": {"anomaly_detected": True},
            "source": "agent.ds",
        }})
        assert result["status"] == "intelligence_collected"
        assert result["cycle_complete"] is True
        assert result["_callsign"] == "CIPHER"

    def test_fuse_reports(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-cipher-2", "sg", "Fuse intelligence")
        result = EXPANSION_STUBS["sg"].handle(task, {"payload": {
            "action": "fuse",
            "reports": [
                {"discipline": "sigint", "data": {"target": "x"}, "source": "a"},
                {"discipline": "osint", "data": {"target": "x"}, "source": "b"},
            ],
        }})
        assert result["status"] == "fusion_complete"
        assert result["total_reports"] >= 2

    def test_zero_day_scan(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-cipher-3", "sg", "Scan predictions")
        result = EXPANSION_STUBS["sg"].handle(task, {"payload": {
            "action": "scan_zero_day",
            "predictions": [100, 101, 99, 102, 98],
        }})
        assert result["status"] == "zero_day_scanned"
        assert "zero_day_clear" in result

    def test_doctrine_score(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-cipher-4", "sg", "Score doctrine")
        result = EXPANSION_STUBS["sg"].handle(task, {"payload": {
            "action": "doctrine_score",
            "context": {"collection_active": True, "red_team_enabled": True},
        }})
        assert result["status"] == "doctrine_scored"
        assert result["doctrine"] == "Unit 8200"

    def test_default_readiness(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-cipher-5", "sg", "Readiness report")
        result = EXPANSION_STUBS["sg"].handle(task, {"payload": {"action": "readiness"}})
        assert result["status"] == "readiness_report"
        assert "readiness_score" in result


class TestAegisAgent:

    def test_red_team(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-aegis-1", "rd", "Red team predictions")
        result = EXPANSION_STUBS["rd"].handle(task, {"payload": {
            "action": "red_team",
            "predictions": [100, 101, 99, 102, 98],
        }})
        assert result["status"] == "red_team_complete"
        assert "zero_day" in result
        assert result["_callsign"] == "AEGIS"

    def test_probe(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-aegis-2", "rd", "Probe model")
        result = EXPANSION_STUBS["rd"].handle(task, {"payload": {
            "action": "probe",
            "target": "model_v1",
            "method": "boundary_probe",
            "params": {"test_values": [0, float("nan")]},
        }})
        assert result["status"] == "probe_complete"
        assert "vulnerability_found" in result

    def test_defend(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-aegis-3", "rd", "Defend against drift")
        result = EXPANSION_STUBS["rd"].handle(task, {"payload": {
            "action": "defend",
            "threat_type": "drift",
        }})
        assert result["status"] == "defense_activated"
        assert result["action"] == "trigger_retraining"

    def test_stress_test(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-aegis-4", "rd", "Stress test")
        result = EXPANSION_STUBS["rd"].handle(task, {"payload": {
            "action": "stress_test",
            "predictions": [100, 101, 99, 102, 98],
        }})
        assert result["status"] == "stress_test_complete"
        assert result["levels_tested"] == 5

    def test_threat_assessment(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-aegis-5", "rd", "Threat assess")
        result = EXPANSION_STUBS["rd"].handle(task, {"payload": {
            "action": "threat_assessment",
        }})
        assert result["status"] == "threat_assessed"
        assert result["total_threats"] >= 5  # Pre-seeded threats

    def test_default_summary(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        task = Task("T-aegis-6", "rd", "Summary")
        result = EXPANSION_STUBS["rd"].handle(task, {"payload": {"action": "summary"}})
        assert result["status"] == "redteam_summary"
        assert "total_probes" in result


# ── Roster Integration Tests ───────────────────────────────────

class TestUnit8200Roster:

    def test_cipher_in_roster(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        cipher = get_agent("sg")
        assert cipher is not None
        assert cipher.callsign == "CIPHER"
        assert cipher.name == "SIGINT Intelligence Analyst"

    def test_aegis_in_roster(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        aegis = get_agent("rd")
        assert aegis is not None
        assert aegis.callsign == "AEGIS"
        assert aegis.name == "Red Team Defense Shield"

    def test_callsign_map(self):
        from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
        assert CALLSIGN_MAP["sg"] == "CIPHER"
        assert CALLSIGN_MAP["rd"] == "AEGIS"

    def test_total_agents_26(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_expansion_pack_17(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        assert len(EXPANSION_PACK) == 21

    def test_cipher_capabilities(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        cipher = get_agent("sg")
        assert cipher is not None
        assert len(cipher.capabilities) == 5
        assert any("TCPED" in c for c in cipher.capabilities)

    def test_aegis_capabilities(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        aegis = get_agent("rd")
        assert aegis is not None
        assert len(aegis.capabilities) == 5
        assert any("Red team" in c for c in aegis.capabilities)

    def test_cipher_langgraph_nodes(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        cipher = get_agent("sg")
        assert cipher is not None
        assert "sigint_collect" in cipher.langgraph_nodes
        assert "sigint_fuse" in cipher.langgraph_nodes

    def test_aegis_langgraph_nodes(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        aegis = get_agent("rd")
        assert aegis is not None
        assert "redteam_probe" in aegis.langgraph_nodes
        assert "blueteam_defend" in aegis.langgraph_nodes

    def test_both_agents_expansion_tier(self):
        from ncl_agency_runtime.fpc.agents import AgentTier, get_agent
        for code in ["sg", "rd"]:
            agent = get_agent(code)
            assert agent is not None
            assert agent.tier == AgentTier.EXPANSION


# ── EventType Tests ────────────────────────────────────────────

class TestUnit8200EventTypes:

    def test_sigint_events(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.SIGINT_COLLECTION == "sigint.collection"
        assert EventType.SIGINT_FUSION == "sigint.fusion"
        assert EventType.SIGINT_ANOMALY == "sigint.anomaly"
        assert EventType.SIGINT_DISSEMINATION == "sigint.dissemination"

    def test_redteam_events(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.REDTEAM_PROBE == "redteam.probe"
        assert EventType.REDTEAM_FINDING == "redteam.finding"

    def test_blueteam_events(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BLUETEAM_DEFENSE == "blueteam.defense"

    def test_doctrine_event(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.UNIT8200_DOCTRINE == "unit8200.doctrine"

    def test_all_8200_events_in_enum(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        values = [e.value for e in EventType]
        expected = [
            "sigint.collection", "sigint.fusion", "sigint.anomaly",
            "sigint.dissemination", "redteam.probe", "redteam.finding",
            "blueteam.defense", "unit8200.doctrine",
        ]
        for ev in expected:
            assert ev in values, f"{ev} missing from EventType enum"
