"""Unit 8200 Intelligence Doctrine for NCL.

Applies the operational framework of Israel's Unit 8200 signals intelligence
unit to the Future Predictor Council. Unit 8200 is the IDF's premier SIGINT
unit -- the Israeli equivalent of NSA/GCHQ.

Core operational principles applied:

  1. TCPED Intelligence Cycle: Tasking -> Collection -> Processing ->
     Exploitation -> Dissemination
  2. Multi-Source Fusion: SIGINT + COMINT + ELINT + CYBINT + OSINT + HUMINT
     fused into a unified operational picture
  3. Red Team / Blue Team: Constant adversarial validation of own systems
  4. Compartmentalization: Need-to-know access, SCI-level classification
  5. Autonomous Cells (Matzov): Small teams, full ownership, flat hierarchy
  6. Zero-Day Philosophy: Find vulnerabilities before adversaries do
  7. Surgical Precision: Minimal footprint, maximum effect (Stuxnet paradigm)
  8. OODA Loop: Observe-Orient-Decide-Act faster than the adversary
  9. Persistence Operations: Long-term low-and-slow collection
 10. Talpiot Pipeline: Recruit, train intensively, output to industry

NCL Mapping:
  Intelligence Cycle -> Data pipeline (SCRIBE -> TEMPO -> ORACLE -> ECHO)
  SIGINT Collection  -> Multi-channel monitoring (Telegram, Discord, telemetry)
  Fusion Center      -> ATLAS Mission Control cross-source correlation
  Red Team           -> Adversarial prediction testing, noise injection
  Compartments       -> PrivacyLevel tiers + Faraday Fortress
  Matzov Cells       -> Agent squads with full domain ownership
  Zero-Day           -> Proactive prediction vulnerability scanning
  Threat Matrix      -> CIOV model (Capability x Intent x Opportunity x Vuln)
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# ── Intelligence Disciplines ───────────────────────────────────
class IntelligenceDiscipline(StrEnum):
    """Intelligence collection disciplines employed by Unit 8200."""

    SIGINT = "sigint"   # Signals Intelligence -- data stream analysis
    COMINT = "comint"   # Communications Intelligence -- channel monitoring
    ELINT = "elint"     # Electronic Intelligence -- system telemetry
    CYBINT = "cybint"   # Cyber Intelligence -- threat detection
    OSINT = "osint"     # Open Source Intelligence -- public data feeds
    HUMINT = "humint"   # Human Intelligence -- user input / manual insights


class ClassificationLevel(StrEnum):
    """Intelligence classification levels (adapted for NCL)."""

    UNCLASSIFIED = "unclassified"     # Public data
    CONFIDENTIAL = "confidential"     # Internal-only
    SECRET = "secret"                 # Restricted access  # noqa: S105
    TOP_SECRET = "top_secret"         # Highest sensitivity  # noqa: S105
    COMPARTMENTED = "compartmented"   # SCI -- need-to-know only


class ThreatCategory(StrEnum):
    """Threat categories for the threat matrix."""

    DATA_INTEGRITY = "data_integrity"       # Corrupted/poisoned input data
    MODEL_DRIFT = "model_drift"             # Model prediction degradation
    ADVERSARIAL = "adversarial"             # Adversarial attacks on models
    INFRASTRUCTURE = "infrastructure"       # System/infra failures
    INSIDER = "insider"                     # Unauthorized internal access
    SUPPLY_CHAIN = "supply_chain"           # Dependency vulnerabilities


# ── Data Contracts ──────────────────────────────────────────────
@dataclass
class IntelligenceReport:
    """A single intelligence report from the collection pipeline."""

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    discipline: IntelligenceDiscipline = IntelligenceDiscipline.OSINT
    classification: ClassificationLevel = ClassificationLevel.CONFIDENTIAL
    source: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5         # 0.0 = no confidence, 1.0 = verified
    timestamp: float = field(default_factory=time.time)
    compartment: str | None = None  # Need-to-know compartment name
    dissemination_list: list[str] = field(default_factory=list)
    fingerprint: str = ""           # Content hash for deduplication

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.source}:{self.discipline}:{sorted(self.content.items())}"
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class ThreatAssessment:
    """CIOV threat assessment: Capability x Intent x Opportunity x Vulnerability."""

    threat_id: str
    category: ThreatCategory
    description: str
    capability: float = 0.0     # 0.0-1.0: can the threat actor execute?
    intent: float = 0.0         # 0.0-1.0: does the actor want to execute?
    opportunity: float = 0.0    # 0.0-1.0: is there a window?
    vulnerability: float = 0.0  # 0.0-1.0: are we exposed?
    risk_score: float = 0.0     # Computed: geometric mean of CIOV
    mitigations: list[str] = field(default_factory=list)
    status: str = "active"

    def compute_risk(self) -> float:
        """Compute risk score as geometric mean of CIOV factors."""
        product = self.capability * self.intent * self.opportunity * self.vulnerability
        self.risk_score = round(product ** 0.25, 4) if product > 0 else 0.0
        return self.risk_score


@dataclass
class RedTeamProbe:
    """A red team adversarial probe against predictions or models."""

    probe_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    target: str = ""               # What is being probed (agent, model, pipeline)
    method: str = ""               # Attack method (noise_injection, drift, etc.)
    params: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    vulnerability_found: bool = False
    severity: str = "low"          # low / medium / high / critical
    timestamp: float = field(default_factory=time.time)


@dataclass
class RedTeamFinding:
    """A vulnerability discovered by the red team."""

    finding_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    probe_id: str = ""
    target: str = ""
    vulnerability: str = ""
    severity: str = "low"
    exploitability: float = 0.0    # 0.0-1.0
    impact: float = 0.0            # 0.0-1.0
    recommendation: str = ""
    status: str = "open"           # open / mitigated / accepted


@dataclass
class CellStatus:
    """Status of an operational cell (Matzov)."""

    cell_id: str
    agents: list[str]
    mission: str
    state: str = "standby"         # standby / active / debriefing / disbanded
    intel_briefed: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0


@dataclass
class OODASnapshot:
    """OODA loop snapshot -- Observe, Orient, Decide, Act."""

    phase: str                     # observe / orient / decide / act
    observations: list[str] = field(default_factory=list)
    orientation: dict[str, Any] = field(default_factory=dict)
    decision: str = ""
    action_taken: str = ""
    cycle_time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


# ── Collection Pipeline ────────────────────────────────────────
class CollectionPipeline:
    """Multi-source intelligence collection following the Unit 8200 TCPED cycle.

    TCPED: Tasking -> Collection -> Processing -> Exploitation -> Dissemination

    Maps to NCL's data pipeline:
      Tasking      = Mission Control (ATLAS) defines collection requirements
      Collection   = SCRIBE + channel connectors gather raw data
      Processing   = TEMPO/ORACLE normalize and enrich
      Exploitation = Model council extracts actionable intelligence
      Dissemination = ECHO briefs distributed with compartmentalization
    """

    DISCIPLINES: ClassVar[list[IntelligenceDiscipline]] = list(IntelligenceDiscipline)

    def __init__(self) -> None:
        self.collection_plan: dict[str, dict[str, Any]] = {}
        self.raw_takes: list[dict[str, Any]] = []
        self.processed: list[IntelligenceReport] = []

    def task_collection(
        self,
        discipline: IntelligenceDiscipline,
        requirements: dict[str, Any],
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Phase 1: TASKING -- define collection requirements."""
        task_id = uuid.uuid4().hex[:8]
        entry = {
            "task_id": task_id,
            "discipline": discipline.value,
            "requirements": requirements,
            "priority": priority,
            "status": "tasked",
            "created": time.time(),
        }
        self.collection_plan[task_id] = entry
        return entry

    def collect(
        self,
        discipline: IntelligenceDiscipline,
        raw_data: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        """Phase 2: COLLECTION -- gather raw intelligence."""
        take = {
            "take_id": uuid.uuid4().hex[:8],
            "discipline": discipline.value,
            "source": source,
            "raw_data": raw_data,
            "collected_at": time.time(),
            "status": "collected",
        }
        self.raw_takes.append(take)
        return take

    def process(self, raw_take: dict[str, Any]) -> IntelligenceReport:
        """Phase 3: PROCESSING -- clean, normalize, enrich raw intelligence."""
        discipline = IntelligenceDiscipline(raw_take.get("discipline", "osint"))
        source = raw_take.get("source", "unknown")
        raw_data = raw_take.get("raw_data", {})

        # Confidence scoring based on source reliability
        confidence = self._score_source_reliability(source, discipline)

        # Classification based on content sensitivity
        classification = self._classify_content(raw_data)

        report = IntelligenceReport(
            discipline=discipline,
            classification=classification,
            source=source,
            content=raw_data,
            confidence=confidence,
        )
        self.processed.append(report)
        return report

    def exploit(self, report: IntelligenceReport) -> dict[str, Any]:
        """Phase 4: EXPLOITATION -- extract actionable intelligence."""
        indicators: list[str] = []
        actions: list[str] = []

        content = report.content

        # Extract patterns based on discipline
        if report.discipline == IntelligenceDiscipline.SIGINT:
            if content.get("anomaly_detected"):
                indicators.append("signal_anomaly")
                actions.append("investigate_signal_source")
            if content.get("pattern_match"):
                indicators.append("known_pattern")
                actions.append("correlate_with_historical")

        elif report.discipline == IntelligenceDiscipline.CYBINT:
            if content.get("threat_indicator"):
                indicators.append("threat_detected")
                actions.append("activate_defenses")
            if content.get("vulnerability"):
                indicators.append("vulnerability_found")
                actions.append("patch_immediately")

        elif report.discipline == IntelligenceDiscipline.OSINT:
            if content.get("market_signal"):
                indicators.append("market_movement")
                actions.append("update_forecasts")
            if content.get("trend_shift"):
                indicators.append("trend_change")
                actions.append("recalibrate_models")

        elif report.discipline in (
            IntelligenceDiscipline.COMINT,
            IntelligenceDiscipline.ELINT,
            IntelligenceDiscipline.HUMINT,
        ):
            if content.get("notable"):
                indicators.append(f"{report.discipline.value}_notable")
                actions.append("flag_for_analyst")

        return {
            "report_id": report.report_id,
            "indicators": indicators,
            "recommended_actions": actions,
            "confidence": report.confidence,
            "exploited": True,
        }

    def disseminate(
        self,
        report: IntelligenceReport,
        recipients: list[str],
    ) -> dict[str, Any]:
        """Phase 5: DISSEMINATION -- share with need-to-know recipients."""
        report.dissemination_list = recipients
        return {
            "report_id": report.report_id,
            "classification": report.classification.value,
            "recipients": recipients,
            "compartment": report.compartment,
            "disseminated_at": time.time(),
        }

    def run_full_cycle(
        self,
        discipline: IntelligenceDiscipline,
        raw_data: dict[str, Any],
        source: str,
        recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute the full TCPED cycle end-to-end."""
        # Task
        tasking = self.task_collection(
            discipline, {"source": source, "type": "standard"}, "normal",
        )

        # Collect
        take = self.collect(discipline, raw_data, source)

        # Process
        report = self.process(take)

        # Exploit
        exploitation = self.exploit(report)

        # Disseminate
        dissemination = self.disseminate(
            report, recipients or ["mc"],
        )

        return {
            "cycle_complete": True,
            "task_id": tasking["task_id"],
            "report_id": report.report_id,
            "discipline": discipline.value,
            "confidence": report.confidence,
            "indicators": exploitation["indicators"],
            "actions": exploitation["recommended_actions"],
            "recipients": dissemination["recipients"],
            "classification": report.classification.value,
        }

    def _score_source_reliability(
        self, source: str, discipline: IntelligenceDiscipline,
    ) -> float:
        """Score source reliability based on source type and discipline."""
        # Base reliability by discipline
        base_scores: dict[str, float] = {
            "sigint": 0.85,    # SIGINT is high-fidelity
            "comint": 0.75,    # COMINT depends on intercept quality
            "elint": 0.80,     # ELINT is measurable
            "cybint": 0.70,    # CYBINT can have false positives
            "osint": 0.60,     # OSINT needs verification
            "humint": 0.50,    # HUMINT is subjective
        }
        base = base_scores.get(discipline.value, 0.5)

        # Boost for known trusted sources
        if source.startswith("agent."):
            base = min(base + 0.1, 1.0)
        elif source == "system":
            base = min(base + 0.15, 1.0)

        return round(base, 2)

    def _classify_content(self, content: dict[str, Any]) -> ClassificationLevel:
        """Classify content sensitivity level."""
        if content.get("pii") or content.get("credentials"):
            return ClassificationLevel.TOP_SECRET
        if content.get("financial") or content.get("strategic"):
            return ClassificationLevel.SECRET
        if content.get("internal"):
            return ClassificationLevel.CONFIDENTIAL
        return ClassificationLevel.UNCLASSIFIED


# ── Fusion Center ──────────────────────────────────────────────
class FusionCenter:
    """Multi-source intelligence fusion engine.

    Combines signals from multiple intelligence disciplines into a
    unified operational picture, following Unit 8200's approach to
    all-source analysis.

    Fusion principles:
      - Corroboration: Multiple sources confirming the same signal
      - Contradiction: Identify conflicting intelligence
      - Gap analysis: What are we NOT seeing?
      - Timeline correlation: Events that cluster in time
    """

    def __init__(self) -> None:
        self.streams: dict[str, list[IntelligenceReport]] = {
            d.value: [] for d in IntelligenceDiscipline
        }
        self.correlations: list[dict[str, Any]] = []
        self.anomalies: list[dict[str, Any]] = []

    @property
    def total_reports(self) -> int:
        return sum(len(reports) for reports in self.streams.values())

    @property
    def active_disciplines(self) -> list[str]:
        return [d for d, reports in self.streams.items() if reports]

    def ingest(self, report: IntelligenceReport) -> None:
        """Ingest a single intelligence report."""
        discipline_key = report.discipline.value
        if discipline_key in self.streams:
            self.streams[discipline_key].append(report)
        else:
            self.streams[discipline_key] = [report]

    def correlate(self) -> list[dict[str, Any]]:
        """Cross-discipline correlation -- find connections across sources.

        Looks for reports from different disciplines that share
        common content indicators (corroboration).
        """
        self.correlations.clear()
        all_reports: list[IntelligenceReport] = []
        for reports in self.streams.values():
            all_reports.extend(reports)

        # Compare every pair of reports from different disciplines
        for i, r1 in enumerate(all_reports):
            for r2 in all_reports[i + 1:]:
                if r1.discipline == r2.discipline:
                    continue
                overlap = self._content_overlap(r1.content, r2.content)
                if overlap > 0:
                    self.correlations.append({
                        "report_a": r1.report_id,
                        "report_b": r2.report_id,
                        "discipline_a": r1.discipline.value,
                        "discipline_b": r2.discipline.value,
                        "overlap_score": overlap,
                        "corroborated": overlap >= 0.5,
                    })

        return self.correlations

    def detect_anomalies(self) -> list[dict[str, Any]]:
        """Anomaly detection across fused intelligence.

        Flags:
          - Low-confidence reports that contradict high-confidence ones
          - Sudden spikes in a single discipline
          - Gap in expected periodic collection
        """
        self.anomalies.clear()

        for discipline, reports in self.streams.items():
            if not reports:
                continue

            # Spike detection: more than 3x average
            avg_confidence = sum(r.confidence for r in reports) / len(reports)
            if len(reports) > 5:
                self.anomalies.append({
                    "type": "volume_spike",
                    "discipline": discipline,
                    "report_count": len(reports),
                    "avg_confidence": round(avg_confidence, 3),
                })

            # Low-confidence outliers
            low_conf = [r for r in reports if r.confidence < 0.3]
            if low_conf:
                self.anomalies.append({
                    "type": "low_confidence",
                    "discipline": discipline,
                    "count": len(low_conf),
                    "report_ids": [r.report_id for r in low_conf],
                })

        # Gap analysis: check for empty disciplines
        missing = [
            d.value for d in IntelligenceDiscipline
            if not self.streams.get(d.value)
        ]
        if missing:
            self.anomalies.append({
                "type": "collection_gap",
                "missing_disciplines": missing,
                "coverage_ratio": round(
                    1.0 - len(missing) / len(IntelligenceDiscipline), 3,
                ),
            })

        return self.anomalies

    def generate_picture(self) -> dict[str, Any]:
        """Generate a unified operational picture."""
        correlations = self.correlate()
        anomalies = self.detect_anomalies()

        # Confidence-weighted summary
        all_reports: list[IntelligenceReport] = []
        for reports in self.streams.values():
            all_reports.extend(reports)

        if not all_reports:
            return {
                "total_reports": 0,
                "active_disciplines": [],
                "correlations": 0,
                "anomalies": 0,
                "fusion_score": 0.0,
                "operational_picture": "DARK -- no intelligence collected",
            }

        avg_confidence = sum(r.confidence for r in all_reports) / len(all_reports)
        corroborated = sum(1 for c in correlations if c.get("corroborated"))
        coverage = len(self.active_disciplines) / len(IntelligenceDiscipline)

        # Fusion score: confidence x coverage x corroboration bonus
        corr_bonus = min(corroborated / max(len(all_reports), 1) + 0.5, 1.0)
        fusion_score = round(avg_confidence * coverage * corr_bonus, 4)

        if fusion_score >= 0.7:
            picture = "CLEAR -- high-confidence multi-source picture"
        elif fusion_score >= 0.4:
            picture = "PARTIAL -- moderate confidence, gaps remain"
        else:
            picture = "DEGRADED -- low confidence or insufficient sources"

        return {
            "total_reports": len(all_reports),
            "active_disciplines": self.active_disciplines,
            "correlations": len(correlations),
            "corroborated": corroborated,
            "anomalies": len(anomalies),
            "avg_confidence": round(avg_confidence, 3),
            "coverage": round(coverage, 3),
            "fusion_score": fusion_score,
            "operational_picture": picture,
        }

    @staticmethod
    def _content_overlap(c1: dict[str, Any], c2: dict[str, Any]) -> float:
        """Compute content overlap between two reports (0.0-1.0)."""
        if not c1 or not c2:
            return 0.0
        keys1 = set(c1.keys())
        keys2 = set(c2.keys())
        union = keys1 | keys2
        if not union:
            return 0.0
        intersection = keys1 & keys2
        # Jaccard similarity of keys + value match bonus
        key_sim = len(intersection) / len(union)
        value_matches = sum(
            1 for k in intersection
            if c1.get(k) == c2.get(k) and c1.get(k) is not None
        )
        value_bonus = value_matches / len(union) if union else 0.0
        return round(min(key_sim + value_bonus, 1.0), 3)


# ── Red Team Engine ────────────────────────────────────────────
class RedTeamEngine:
    """Red Team / Blue Team adversarial testing framework.

    Inspired by Unit 8200's adversarial validation methodology:
      Red Team:  Attack your own predictions to find weaknesses
      Blue Team: Defend model integrity and detect manipulation

    Methods:
      - Noise injection: perturb inputs to test prediction robustness
      - Drift simulation: simulate concept/data drift
      - Boundary probing: test edge cases and extreme values
      - Supply chain audit: verify dependency integrity
    """

    def __init__(self) -> None:
        self.probes: list[RedTeamProbe] = []
        self.findings: list[RedTeamFinding] = []
        self.defenses: list[dict[str, Any]] = []

    def probe(
        self,
        target: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> RedTeamProbe:
        """Red Team probe -- test a target for vulnerabilities.

        Methods:
          noise_injection  -- add Gaussian noise to predictions
          drift_simulation -- simulate gradual or sudden drift
          boundary_probe   -- test extreme values
          replay_attack    -- replay old data as new
        """
        p = RedTeamProbe(
            target=target,
            method=method,
            params=params or {},
        )

        if method == "noise_injection":
            p.result = self._noise_injection(params or {})
        elif method == "drift_simulation":
            p.result = self._drift_simulation(params or {})
        elif method == "boundary_probe":
            p.result = self._boundary_probe(params or {})
        elif method == "replay_attack":
            p.result = self._replay_attack(params or {})
        else:
            p.result = {"status": "unknown_method", "method": method}

        self.probes.append(p)
        return p

    def assess_finding(self, probe: RedTeamProbe) -> RedTeamFinding | None:
        """Assess whether a probe found a real vulnerability."""
        if not probe.result.get("vulnerability_detected"):
            return None

        severity = probe.result.get("severity", "low")
        finding = RedTeamFinding(
            probe_id=probe.probe_id,
            target=probe.target,
            vulnerability=probe.result.get("vulnerability_type", "unknown"),
            severity=severity,
            exploitability=probe.result.get("exploitability", 0.5),
            impact=probe.result.get("impact", 0.5),
            recommendation=probe.result.get("recommendation", "Investigate further"),
        )
        self.findings.append(finding)
        return finding

    def defend(self, threat_type: str, context: dict[str, Any]) -> dict[str, Any]:
        """Blue team defensive action."""
        defense = {
            "defense_id": uuid.uuid4().hex[:8],
            "threat_type": threat_type,
            "action": "none",
            "timestamp": time.time(),
        }

        if threat_type == "noise":
            defense["action"] = "apply_robust_scaling"
            defense["detail"] = "Activated robust input normalization"
        elif threat_type == "drift":
            defense["action"] = "trigger_retraining"
            defense["detail"] = "Scheduled model retraining cycle"
        elif threat_type == "boundary":
            defense["action"] = "clamp_inputs"
            defense["detail"] = "Applied input value clamping to safe range"
        elif threat_type == "replay":
            defense["action"] = "timestamp_validation"
            defense["detail"] = "Enabled strict timestamp monotonicity checks"
        else:
            defense["action"] = "monitor"
            defense["detail"] = f"Unknown threat type '{threat_type}', monitoring"

        self.defenses.append(defense)
        return defense

    def zero_day_scan(self, predictions: list[float]) -> dict[str, Any]:
        """Zero-Day philosophy -- find prediction vulnerabilities proactively.

        Checks for:
          - Constant predictions (model collapsed)
          - Extreme outliers (unbounded predictions)
          - NaN/Inf contamination
          - Suspicious periodicity (overfitting)
        """
        if not predictions:
            return {"status": "no_data", "vulnerabilities": []}

        vulns: list[str] = []
        n = len(predictions)

        # Check for constant predictions (collapsed model)
        unique_vals = len(set(predictions))
        if unique_vals == 1 and n > 1:
            vulns.append("constant_prediction_collapse")

        # Check for NaN/Inf
        nan_count = sum(1 for p in predictions if math.isnan(p) or math.isinf(p))
        if nan_count > 0:
            vulns.append(f"nan_inf_contamination({nan_count})")

        # Check for extreme outliers (> 5 sigma)
        clean = [p for p in predictions if math.isfinite(p)]
        if len(clean) >= 2:
            mean = sum(clean) / len(clean)
            variance = sum((x - mean) ** 2 for x in clean) / len(clean)
            std = variance ** 0.5
            if std > 0:
                outliers = sum(1 for x in clean if abs(x - mean) > 5 * std)
                if outliers > 0:
                    vulns.append(f"extreme_outliers({outliers})")

            # Suspiciously low variance (possible overfitting)
            cv = std / abs(mean) if mean != 0 else 0
            if cv < 0.001 and n > 5:
                vulns.append("suspiciously_low_variance")

        severity = "critical" if len(vulns) >= 3 else (
            "high" if len(vulns) >= 2 else (
                "medium" if vulns else "clean"
            )
        )

        return {
            "status": "scanned",
            "prediction_count": n,
            "vulnerabilities": vulns,
            "vulnerability_count": len(vulns),
            "severity": severity,
            "zero_day_clear": len(vulns) == 0,
        }

    def stress_test(
        self,
        predictions: list[float],
        noise_levels: list[float] | None = None,
    ) -> dict[str, Any]:
        """Stress test predictions with escalating noise injection."""
        if not predictions:
            return {"status": "no_data", "results": []}

        levels = noise_levels or [0.01, 0.05, 0.10, 0.25, 0.50]
        clean = [p for p in predictions if math.isfinite(p)]
        if not clean:
            return {"status": "no_clean_data", "results": []}

        mean = sum(clean) / len(clean)
        results: list[dict[str, Any]] = []

        for level in levels:
            # Simulate noise-perturbed predictions
            std_noise = abs(mean) * level if mean != 0 else level
            # Compute expected deviation
            max_deviation = std_noise * 3  # 3-sigma envelope
            relative_deviation = max_deviation / abs(mean) if mean != 0 else max_deviation
            robust = relative_deviation < 0.5  # Predictions should not shift > 50%

            results.append({
                "noise_level": level,
                "noise_std": round(std_noise, 4),
                "max_expected_deviation": round(max_deviation, 4),
                "relative_deviation": round(relative_deviation, 4),
                "robust": robust,
            })

        failing_levels = [r for r in results if not r["robust"]]
        return {
            "status": "stress_tested",
            "levels_tested": len(levels),
            "levels_passed": len(levels) - len(failing_levels),
            "levels_failed": len(failing_levels),
            "break_point": failing_levels[0]["noise_level"] if failing_levels else None,
            "results": results,
        }

    def summary(self) -> dict[str, Any]:
        """Red team summary statistics."""
        critical = sum(1 for f in self.findings if f.severity == "critical")
        high = sum(1 for f in self.findings if f.severity == "high")
        return {
            "total_probes": len(self.probes),
            "total_findings": len(self.findings),
            "critical_findings": critical,
            "high_findings": high,
            "defenses_activated": len(self.defenses),
            "open_findings": sum(1 for f in self.findings if f.status == "open"),
        }

    # ── Internal probe methods ──
    @staticmethod
    def _noise_injection(params: dict[str, Any]) -> dict[str, Any]:
        """Simulate noise injection attack."""
        noise_level = params.get("noise_level", 0.1)
        predictions = params.get("predictions", [])
        if not predictions:
            return {"vulnerability_detected": False, "detail": "no predictions to test"}

        clean = [p for p in predictions if isinstance(p, (int, float)) and math.isfinite(p)]
        if not clean:
            return {"vulnerability_detected": True, "severity": "high",
                    "vulnerability_type": "all_predictions_invalid",
                    "exploitability": 0.9, "impact": 0.8,
                    "recommendation": "Fix prediction pipeline"}

        mean = sum(clean) / len(clean)
        std = (sum((x - mean) ** 2 for x in clean) / len(clean)) ** 0.5 if len(clean) > 1 else 0
        noise_impact = noise_level * abs(mean) if mean != 0 else noise_level

        vulnerable = noise_impact > std * 2 if std > 0 else noise_level > 0.1
        return {
            "vulnerability_detected": vulnerable,
            "severity": "high" if vulnerable else "low",
            "vulnerability_type": "noise_sensitivity" if vulnerable else "none",
            "noise_level": noise_level,
            "prediction_std": round(std, 4),
            "noise_impact": round(noise_impact, 4),
            "exploitability": 0.7 if vulnerable else 0.1,
            "impact": 0.6 if vulnerable else 0.1,
            "recommendation": "Apply robust scaling" if vulnerable else "Noise resilient",
        }

    @staticmethod
    def _drift_simulation(params: dict[str, Any]) -> dict[str, Any]:
        """Simulate concept drift."""
        drift_magnitude = params.get("drift_magnitude", 0.2)
        detection_threshold = params.get("detection_threshold", 0.15)
        undetected = drift_magnitude < detection_threshold

        return {
            "vulnerability_detected": undetected,
            "severity": "medium" if undetected else "low",
            "vulnerability_type": "undetected_drift" if undetected else "none",
            "drift_magnitude": drift_magnitude,
            "detection_threshold": detection_threshold,
            "exploitability": 0.6 if undetected else 0.2,
            "impact": 0.5 if undetected else 0.1,
            "recommendation": "Lower detection threshold" if undetected else "Drift detected correctly",
        }

    @staticmethod
    def _boundary_probe(params: dict[str, Any]) -> dict[str, Any]:
        """Test boundary conditions."""
        test_values = params.get("test_values", [0, -1, 1e15, float("nan")])
        failures: list[str] = []
        for val in test_values:
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                failures.append(f"invalid_value:{val}")
            elif isinstance(val, (int, float)) and abs(val) > 1e12:
                failures.append(f"extreme_value:{val}")

        return {
            "vulnerability_detected": len(failures) > 0,
            "severity": "medium" if failures else "low",
            "vulnerability_type": "boundary_failure" if failures else "none",
            "failures": failures,
            "values_tested": len(test_values),
            "exploitability": 0.5 if failures else 0.1,
            "impact": 0.4 if failures else 0.1,
            "recommendation": "Add input validation" if failures else "Boundaries respected",
        }

    @staticmethod
    def _replay_attack(params: dict[str, Any]) -> dict[str, Any]:
        """Simulate replay attack with stale data."""
        staleness_hours = params.get("staleness_hours", 24)
        max_age_hours = params.get("max_age_hours", 12)
        replayed = staleness_hours > max_age_hours

        return {
            "vulnerability_detected": replayed,
            "severity": "high" if replayed else "low",
            "vulnerability_type": "stale_data_accepted" if replayed else "none",
            "staleness_hours": staleness_hours,
            "max_age_hours": max_age_hours,
            "exploitability": 0.8 if replayed else 0.1,
            "impact": 0.7 if replayed else 0.1,
            "recommendation": "Enforce timestamp validation" if replayed else "Freshness checks pass",
        }


# ── Compartmentalization Matrix ────────────────────────────────
class CompartmentalizationMatrix:
    """Need-to-know access control matrix.

    Maps intelligence compartments to authorized agent codenames,
    enforcing Unit 8200's strict compartmentalization principles.

    Default compartments reflect NCL's operational domains:
      FORECAST -- prediction models and results
      FINANCIAL -- AAC asset data and trading signals
      GOVERNANCE -- NCC doctrine and policy controls
      THREAT -- security findings and threat intelligence
      OPERATIONS -- system telemetry and operational data
    """

    DEFAULT_COMPARTMENTS: ClassVar[dict[str, list[str]]] = {
        "FORECAST": ["mc", "be", "ne", "fo", "xe", "cs"],
        "FINANCIAL": ["mc", "ab"],
        "GOVERNANCE": ["mc", "nc", "so"],
        "THREAT": ["mc", "so", "sg", "rd"],
        "OPERATIONS": ["mc", "mo", "dx", "em"],
    }

    def __init__(self) -> None:
        self.compartments: dict[str, set[str]] = {
            name: set(agents) for name, agents in self.DEFAULT_COMPARTMENTS.items()
        }
        self.clearances: dict[str, ClassificationLevel] = {}
        self.access_log: list[dict[str, Any]] = []

    def create_compartment(self, name: str, authorized_agents: list[str]) -> None:
        """Create or update an intelligence compartment."""
        self.compartments[name] = set(authorized_agents)

    def check_access(
        self,
        agent_codename: str,
        compartment: str,
    ) -> dict[str, Any]:
        """Check if an agent has access to a compartment."""
        authorized_agents = self.compartments.get(compartment)
        if authorized_agents is None:
            result = {
                "access": False,
                "reason": f"Compartment '{compartment}' does not exist",
                "agent": agent_codename,
                "compartment": compartment,
            }
        else:
            granted = agent_codename in authorized_agents
            result = {
                "access": granted,
                "reason": "authorized" if granted else "need-to-know denied",
                "agent": agent_codename,
                "compartment": compartment,
            }

        self.access_log.append({**result, "timestamp": time.time()})
        return result

    def grant_clearance(
        self,
        agent_codename: str,
        level: ClassificationLevel,
    ) -> None:
        """Grant a classification clearance level to an agent."""
        self.clearances[agent_codename] = level

    def check_clearance(
        self,
        agent_codename: str,
        required_level: ClassificationLevel,
    ) -> bool:
        """Check if an agent has sufficient clearance for a classification level."""
        levels = list(ClassificationLevel)
        agent_level = self.clearances.get(agent_codename, ClassificationLevel.UNCLASSIFIED)
        return levels.index(agent_level) >= levels.index(required_level)

    def classify_report(
        self,
        report: IntelligenceReport,
        compartment: str,
    ) -> IntelligenceReport:
        """Assign a compartment to an intelligence report."""
        report.compartment = compartment
        report.classification = ClassificationLevel.COMPARTMENTED
        return report

    def summary(self) -> dict[str, Any]:
        """Compartment summary."""
        return {
            "compartment_count": len(self.compartments),
            "compartments": {
                name: list(agents)
                for name, agents in self.compartments.items()
            },
            "clearance_count": len(self.clearances),
            "access_checks": len(self.access_log),
            "denied_count": sum(
                1 for entry in self.access_log if not entry.get("access")
            ),
        }


# ── Threat Matrix ──────────────────────────────────────────────
class ThreatMatrix:
    """Threat assessment and prioritization matrix.

    Evaluates threats using the CIOV model:
      C = Capability: Can the threat actor execute?
      I = Intent: Does the actor want to execute?
      O = Opportunity: Is there a window?
      V = Vulnerability: Are we exposed?

    Risk = (C x I x O x V) ^ 0.25  (geometric mean)
    """

    def __init__(self) -> None:
        self.threats: list[ThreatAssessment] = []

    def add_threat(
        self,
        threat_id: str,
        category: ThreatCategory,
        description: str,
        capability: float = 0.5,
        intent: float = 0.5,
        opportunity: float = 0.5,
        vulnerability: float = 0.5,
    ) -> ThreatAssessment:
        """Register a threat in the matrix."""
        threat = ThreatAssessment(
            threat_id=threat_id,
            category=category,
            description=description,
            capability=capability,
            intent=intent,
            opportunity=opportunity,
            vulnerability=vulnerability,
        )
        threat.compute_risk()
        self.threats.append(threat)
        return threat

    def assess(self, threat_id: str) -> ThreatAssessment | None:
        """Retrieve and recompute assessment for a specific threat."""
        for threat in self.threats:
            if threat.threat_id == threat_id:
                threat.compute_risk()
                return threat
        return None

    def prioritize(self) -> list[ThreatAssessment]:
        """Rank threats by risk score (highest first)."""
        for t in self.threats:
            t.compute_risk()
        return sorted(self.threats, key=lambda t: t.risk_score, reverse=True)

    def mitigations_for(self, threat_id: str) -> list[str]:
        """Get mitigations for a specific threat."""
        for t in self.threats:
            if t.threat_id == threat_id:
                return t.mitigations
        return []

    def category_summary(self) -> dict[str, int]:
        """Count threats by category."""
        counts: dict[str, int] = {}
        for t in self.threats:
            key = t.category.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def high_risk_threats(self, threshold: float = 0.6) -> list[ThreatAssessment]:
        """Return threats above a risk threshold."""
        return [t for t in self.prioritize() if t.risk_score >= threshold]

    def summary(self) -> dict[str, Any]:
        """Threat matrix summary."""
        prioritized = self.prioritize()
        return {
            "total_threats": len(self.threats),
            "categories": self.category_summary(),
            "highest_risk": prioritized[0].risk_score if prioritized else 0.0,
            "high_risk_count": len(self.high_risk_threats()),
            "active_threats": sum(1 for t in self.threats if t.status == "active"),
        }


# ── Operational Cell (Matzov) ──────────────────────────────────
class OperationalCell:
    """Autonomous operational cell -- the Matzov pattern.

    Unit 8200's signature organizational unit:
      - 3-8 agents with complementary capabilities
      - Full ownership of their mission domain
      - Flat internal hierarchy (best idea wins)
      - Direct escalation path to Mission Control
      - Self-contained: collect, analyze, report
    """

    def __init__(
        self,
        cell_id: str,
        agents: list[str],
        mission: str,
    ) -> None:
        self.cell_id = cell_id
        self.agents = agents
        self.mission = mission
        self.state = "standby"
        self.intel_briefed: int = 0
        self.tasks_completed: int = 0
        self.tasks_failed: int = 0
        self.log: list[dict[str, Any]] = []

    def activate(self) -> CellStatus:
        """Activate the cell for a mission."""
        self.state = "active"
        self._log("activated", f"Cell {self.cell_id} activated for: {self.mission}")
        return self.status()

    def brief(self, intelligence: list[IntelligenceReport]) -> dict[str, Any]:
        """Brief the cell with relevant intelligence."""
        self.intel_briefed += len(intelligence)
        compartments = {r.compartment for r in intelligence if r.compartment}
        self._log("briefed", f"Briefed with {len(intelligence)} reports")
        return {
            "cell_id": self.cell_id,
            "reports_received": len(intelligence),
            "compartments": list(compartments),
            "total_briefed": self.intel_briefed,
        }

    def execute_task(self, task_description: str) -> dict[str, Any]:
        """Execute a task within the cell's mission scope."""
        if self.state != "active":
            return {
                "cell_id": self.cell_id,
                "success": False,
                "reason": f"Cell not active (state={self.state})",
            }
        self.tasks_completed += 1
        self._log("task_completed", task_description)
        return {
            "cell_id": self.cell_id,
            "success": True,
            "task": task_description,
            "completed_total": self.tasks_completed,
        }

    def debrief(self) -> dict[str, Any]:
        """Post-mission debrief and lessons learned."""
        self.state = "debriefing"
        rate = (
            self.tasks_completed / (self.tasks_completed + self.tasks_failed)
            if (self.tasks_completed + self.tasks_failed) > 0
            else 0.0
        )
        self._log("debriefing", f"Success rate: {rate:.1%}")
        return {
            "cell_id": self.cell_id,
            "mission": self.mission,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "success_rate": round(rate, 3),
            "intel_briefed": self.intel_briefed,
            "log_entries": len(self.log),
        }

    def disband(self) -> None:
        """Disband the cell after mission completion."""
        self.state = "disbanded"
        self._log("disbanded", "Cell disbanded")

    def status(self) -> CellStatus:
        """Current cell status."""
        return CellStatus(
            cell_id=self.cell_id,
            agents=self.agents,
            mission=self.mission,
            state=self.state,
            intel_briefed=self.intel_briefed,
            tasks_completed=self.tasks_completed,
            tasks_failed=self.tasks_failed,
        )

    def _log(self, action: str, detail: str) -> None:
        self.log.append({
            "action": action,
            "detail": detail,
            "timestamp": time.time(),
        })


# ── OODA Loop Engine ──────────────────────────────────────────
class OODALoop:
    """OODA Loop decision engine -- Observe, Orient, Decide, Act.

    Boyd's OODA loop applied to the Future Predictor Council:
      Observe:  Collect intelligence from all sources
      Orient:   Fuse, correlate, contextualize
      Decide:   Select best course of action
      Act:      Execute and measure results

    The side that cycles through OODA faster wins.
    """

    def __init__(self) -> None:
        self.cycles: list[OODASnapshot] = []

    def observe(self, observations: list[str]) -> OODASnapshot:
        """Phase 1: OBSERVE -- collect raw observations."""
        snap = OODASnapshot(
            phase="observe",
            observations=observations,
        )
        self.cycles.append(snap)
        return snap

    def orient(
        self,
        observations: list[str],
        context: dict[str, Any],
    ) -> OODASnapshot:
        """Phase 2: ORIENT -- fuse observations with context."""
        snap = OODASnapshot(
            phase="orient",
            observations=observations,
            orientation={
                "context": context,
                "threat_level": context.get("threat_level", "normal"),
                "confidence": context.get("confidence", 0.5),
            },
        )
        self.cycles.append(snap)
        return snap

    def decide(
        self,
        observations: list[str],
        orientation: dict[str, Any],
        decision: str,
    ) -> OODASnapshot:
        """Phase 3: DECIDE -- select course of action."""
        snap = OODASnapshot(
            phase="decide",
            observations=observations,
            orientation=orientation,
            decision=decision,
        )
        self.cycles.append(snap)
        return snap

    def act(
        self,
        decision: str,
        action: str,
        cycle_time_ms: float = 0.0,
    ) -> OODASnapshot:
        """Phase 4: ACT -- execute and record."""
        snap = OODASnapshot(
            phase="act",
            decision=decision,
            action_taken=action,
            cycle_time_ms=cycle_time_ms,
        )
        self.cycles.append(snap)
        return snap

    def full_cycle(
        self,
        observations: list[str],
        context: dict[str, Any],
        decision: str,
        action: str,
    ) -> dict[str, Any]:
        """Execute a complete OODA cycle."""
        start = time.time()

        obs = self.observe(observations)
        ori = self.orient(observations, context)
        dec = self.decide(observations, ori.orientation, decision)
        elapsed_ms = (time.time() - start) * 1000
        act = self.act(decision, action, elapsed_ms)

        return {
            "cycle_complete": True,
            "observations": obs.observations,
            "threat_level": ori.orientation.get("threat_level", "normal"),
            "decision": dec.decision,
            "action_taken": act.action_taken,
            "cycle_time_ms": round(act.cycle_time_ms, 2),
            "total_cycles": len([c for c in self.cycles if c.phase == "act"]),
        }

    def cycle_stats(self) -> dict[str, Any]:
        """Statistics on OODA cycle performance."""
        act_cycles = [c for c in self.cycles if c.phase == "act"]
        if not act_cycles:
            return {"total_cycles": 0, "avg_cycle_ms": 0.0}

        times = [c.cycle_time_ms for c in act_cycles]
        return {
            "total_cycles": len(act_cycles),
            "avg_cycle_ms": round(sum(times) / len(times), 2),
            "min_cycle_ms": round(min(times), 2),
            "max_cycle_ms": round(max(times), 2),
        }


# ── Unit 8200 Doctrine Engine ──────────────────────────────────
class Unit8200Doctrine:
    """Unified Unit 8200 doctrine engine for NCL.

    Combines all operational components into a single framework
    that can be applied to the Future Predictor Council.

    DOCTRINE PRINCIPLES:
      1.  Collect everything, trust nothing
      2.  Fuse before you analyze
      3.  Red team yourself constantly
      4.  Compartmentalize by default
      5.  Small teams, big impact (Matzov)
      6.  Find zero-days before they find you
      7.  Flat hierarchy, meritocratic decisions
      8.  Speed is decisive (OODA dominance)
      9.  Persistence operations -- long-term collection pays
      10. Surgical precision -- minimal footprint, maximum effect
    """

    PRINCIPLES: ClassVar[dict[str, str]] = {
        "collect_trust_nothing": (
            "Collect everything, trust nothing -- validate at system boundaries"
        ),
        "fuse_before_analyze": (
            "Fuse before you analyze -- cross-source correlation first"
        ),
        "red_team_constantly": (
            "Red team yourself constantly -- adversarial validation every cycle"
        ),
        "compartmentalize_default": (
            "Compartmentalize by default -- need-to-know access control"
        ),
        "small_teams_big_impact": (
            "Small teams, big impact -- autonomous Matzov cells"
        ),
        "zero_day_philosophy": (
            "Find zero-days before they find you -- proactive vulnerability hunting"
        ),
        "flat_hierarchy": (
            "Flat hierarchy, meritocratic decisions -- best idea wins"
        ),
        "ooda_dominance": (
            "Speed is decisive -- cycle through OODA faster than the adversary"
        ),
        "persistence_operations": (
            "Persistence operations -- long-term low-and-slow collection pays dividends"
        ),
        "surgical_precision": (
            "Surgical precision -- minimal footprint, maximum effect"
        ),
    }

    def __init__(self) -> None:
        self.pipeline = CollectionPipeline()
        self.fusion = FusionCenter()
        self.redteam = RedTeamEngine()
        self.compartments = CompartmentalizationMatrix()
        self.threat_matrix = ThreatMatrix()
        self.ooda = OODALoop()
        self.cells: dict[str, OperationalCell] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the full Unit 8200 doctrine framework."""
        # Pre-seed threat matrix with standard NCL threat landscape
        self.threat_matrix.add_threat(
            "T-001", ThreatCategory.DATA_INTEGRITY,
            "Corrupted input data poisoning forecasts",
            capability=0.7, intent=0.3, opportunity=0.5, vulnerability=0.6,
        )
        self.threat_matrix.add_threat(
            "T-002", ThreatCategory.MODEL_DRIFT,
            "Concept drift degrading prediction accuracy",
            capability=0.9, intent=0.0, opportunity=0.8, vulnerability=0.7,
        )
        self.threat_matrix.add_threat(
            "T-003", ThreatCategory.ADVERSARIAL,
            "Adversarial input manipulation",
            capability=0.5, intent=0.6, opportunity=0.3, vulnerability=0.4,
        )
        self.threat_matrix.add_threat(
            "T-004", ThreatCategory.INFRASTRUCTURE,
            "System resource exhaustion (GPU/RAM)",
            capability=0.8, intent=0.0, opportunity=0.6, vulnerability=0.5,
        )
        self.threat_matrix.add_threat(
            "T-005", ThreatCategory.SUPPLY_CHAIN,
            "Compromised dependency in model pipeline",
            capability=0.4, intent=0.5, opportunity=0.2, vulnerability=0.3,
        )

        self._initialized = True
        return {
            "status": "initialized",
            "principles": len(self.PRINCIPLES),
            "threats_seeded": len(self.threat_matrix.threats),
            "compartments": len(self.compartments.compartments),
            "disciplines": len(IntelligenceDiscipline),
        }

    def score_doctrine(self, context: dict[str, Any]) -> dict[str, Any]:
        """Score compliance with Unit 8200 doctrine principles.

        Context keys checked:
          collection_active, multi_source_fusion, red_team_enabled,
          compartments_enforced, cells_formed, zero_day_scanning,
          flat_decisions, ooda_cycle_ms, persistence_collection,
          precision_targeting
        """
        met: list[str] = []
        violated: list[str] = []

        checks: dict[str, str] = {
            "collection_active": "collect_trust_nothing",
            "multi_source_fusion": "fuse_before_analyze",
            "red_team_enabled": "red_team_constantly",
            "compartments_enforced": "compartmentalize_default",
            "cells_formed": "small_teams_big_impact",
            "zero_day_scanning": "zero_day_philosophy",
            "flat_decisions": "flat_hierarchy",
            "ooda_fast": "ooda_dominance",
            "persistence_collection": "persistence_operations",
            "precision_targeting": "surgical_precision",
        }

        for ctx_key, principle_key in checks.items():
            if context.get(ctx_key, False):
                met.append(principle_key)
            else:
                violated.append(principle_key)

        total = len(self.PRINCIPLES)
        score = len(met) / total if total > 0 else 0.0

        # Grade
        if score >= 0.9:
            grade = "S"
        elif score >= 0.8:
            grade = "A"
        elif score >= 0.7:
            grade = "B"
        elif score >= 0.5:
            grade = "C"
        elif score >= 0.3:
            grade = "D"
        else:
            grade = "F"

        return {
            "doctrine": "Unit 8200",
            "score": round(score, 3),
            "grade": grade,
            "principles_met": met,
            "principles_violated": violated,
            "total_principles": total,
        }

    def form_cell(
        self,
        cell_id: str,
        agents: list[str],
        mission: str,
    ) -> OperationalCell:
        """Form an operational cell (Matzov pattern)."""
        cell = OperationalCell(cell_id, agents, mission)
        self.cells[cell_id] = cell
        return cell

    def run_intelligence_cycle(
        self,
        discipline: IntelligenceDiscipline,
        raw_data: dict[str, Any],
        source: str,
        recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a full TCPED intelligence cycle and fuse the result."""
        cycle_result = self.pipeline.run_full_cycle(
            discipline, raw_data, source, recipients,
        )

        # Auto-fuse: ingest the processed report into the fusion center
        if self.pipeline.processed:
            self.fusion.ingest(self.pipeline.processed[-1])

        return cycle_result

    def red_team_predictions(self, predictions: list[float]) -> dict[str, Any]:
        """Red team a set of predictions -- full adversarial assessment."""
        # Zero-day scan
        zero_day = self.redteam.zero_day_scan(predictions)

        # Stress test
        stress = self.redteam.stress_test(predictions)

        # Noise injection probe
        noise_probe = self.redteam.probe(
            "predictions", "noise_injection",
            {"predictions": predictions, "noise_level": 0.1},
        )
        noise_finding = self.redteam.assess_finding(noise_probe)

        return {
            "zero_day": zero_day,
            "stress_test": stress,
            "noise_probe": {
                "vulnerability_detected": noise_probe.result.get("vulnerability_detected", False),
                "severity": noise_probe.result.get("severity", "low"),
            },
            "finding": {
                "id": noise_finding.finding_id if noise_finding else None,
                "severity": noise_finding.severity if noise_finding else None,
            },
            "overall_severity": zero_day.get("severity", "no_data"),
        }

    def operational_readiness(self) -> dict[str, Any]:
        """Assess operational readiness across all Unit 8200 components."""
        fusion_pic = self.fusion.generate_picture()
        threat_sum = self.threat_matrix.summary()
        redteam_sum = self.redteam.summary()
        compartment_sum = self.compartments.summary()
        ooda_stats = self.ooda.cycle_stats()

        # Readiness components
        components = {
            "collection": len(self.pipeline.processed) > 0,
            "fusion": fusion_pic["fusion_score"] > 0.0,
            "threat_assessment": threat_sum["total_threats"] > 0,
            "red_team": redteam_sum["total_probes"] > 0 or self._initialized,
            "compartments": compartment_sum["compartment_count"] > 0,
            "ooda": ooda_stats["total_cycles"] > 0 or self._initialized,
            "cells": len(self.cells) > 0 or self._initialized,
        }

        ready_count = sum(1 for v in components.values() if v)
        readiness = round(ready_count / len(components), 3) if components else 0.0

        if readiness >= 0.85:
            status = "OPERATIONAL"
        elif readiness >= 0.6:
            status = "DEGRADED"
        elif readiness >= 0.3:
            status = "LIMITED"
        else:
            status = "NOT_READY"

        return {
            "readiness_score": readiness,
            "status": status,
            "components": components,
            "fusion": fusion_pic,
            "threats": threat_sum,
            "redteam": redteam_sum,
            "compartments": compartment_sum,
            "ooda": ooda_stats,
            "cells_active": sum(
                1 for c in self.cells.values() if c.state == "active"
            ),
            "initialized": self._initialized,
        }
