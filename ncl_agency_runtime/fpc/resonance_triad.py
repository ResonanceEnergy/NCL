"""Resonance Energy Triad: NCC x BRS x AAC integration.

RESONANCE ENERGY = NCC (Governance/BRAIN) x BRS (Execution/AGENCY) x AAC (Assets/BANK)

This module connects NCL's Future Predictor Council to the three pillars:

1. **NCC (Natrix Command & Control)** — Supreme governance layer
   Three Pillars: Art of War, 48 Laws of Power, 7 Habits.
   Faraday Fortress layered security. Doctrine-Lock. PDCA audit loops.

2. **AAC (Autonomous Asset Collective)** — Asset intelligence layer
   8 exchange connectors, 52 strategies, 80+ AI agents.
   Portfolio management, trading signals, strategy performance.

3. **BRS (Bit Rage Systems)** — Execution orchestration layer
   Multi-agent coordination, RBAC governance, skill composition.
   Workflow routing, agent dispatch, capability bridging.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

_NCL_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DOCTRINE_PATH = _NCL_ROOT / "NCC_Master_Doctrine_v2.0.md"


# ── NCC Governance Connector ──────────────────────────────────


@dataclass
class PillarScore:
    """Score for one of the Three Pillars of Mastery."""

    name: str
    score: float  # 0.0 to 1.0
    principles_met: list[str] = field(default_factory=list)
    principles_violated: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if self.score >= 0.9:
            return "S"
        if self.score >= 0.8:
            return "A"
        if self.score >= 0.7:
            return "B"
        if self.score >= 0.6:
            return "C"
        if self.score >= 0.5:
            return "D"
        return "F"


@dataclass
class DoctrineCheckResult:
    """Result of a full doctrine compliance check."""

    compliant: bool
    pillar_scores: list[PillarScore] = field(default_factory=list)
    fortress_layers_ok: list[str] = field(default_factory=list)
    fortress_layers_warn: list[str] = field(default_factory=list)
    doctrine_lock_violations: list[str] = field(default_factory=list)
    resonance_score: float = 0.0


@dataclass
class PDCAAudit:
    """Plan-Do-Check-Act audit result."""

    phase: str  # plan | do | check | act
    findings: list[str] = field(default_factory=list)
    score: float = 0.0
    recommendations: list[str] = field(default_factory=list)


class NCCGovernanceConnector:
    """Connects the council to NCC doctrine governance.

    Loads the NCC Master Doctrine and enforces its principles:
    - Three Pillars scoring (Art of War, 48 Laws, 7 Habits)
    - Faraday Fortress layer validation
    - Doctrine-Lock enforcement (ZERO CLOUD DATA)
    - PDCA audit loops
    """

    # Three Pillars principle maps
    ART_OF_WAR_PRINCIPLES: ClassVar[dict[str, str]] = {
        "terrain_awareness": "Know the terrain — adapt mission routing to data landscape",
        "speed_decisive": "Speed is the essence — dispatch within rate limits",
        "win_without_fighting": "Win without fighting — proactive briefs prevent escalation",
        "know_thyself": "Know yourself — memory analytics reveal blind spots",
        "deception_defence": "Deception defence — zero-trust opaque error responses",
        "prepare_battlefield": "Every battle won before fought — golden task validation",
        "five_factors": "Dao, Heaven, Earth, Commander, Discipline applied",
    }

    LAWS_OF_POWER_PRINCIPLES: ClassVar[dict[str, str]] = {
        "defer_to_master": "Law 1 — agents defer to AZ_PRIME in policy decisions",
        "say_less": "Law 4 — minimal API responses, no verbose error internals",
        "win_through_actions": "Law 9 — evidence-based audit trails prove everything",
        "suspended_terror": "Law 17 — kill switch + lockdown deters abuse",
        "recreate_yourself": "Law 25 — self-healing, memory consolidation is renewal",
        "bold_action": "Law 28 — run_with_retry commits fully, no half-measures",
        "plan_to_end": "Law 29 — full mission lifecycle queued→completed→dead-letter",
        "master_timing": "Law 35 — rate limiting, circadian-aware processing",
        "graceful_degradation": "Law 36 — graceful degradation when subsystems offline",
        "earned_trust": "Law 40 — API keys, consent flows, no anonymous access",
        "formlessness": "Law 48 — channel-agnostic, plugin-based skill architecture",
    }

    SEVEN_HABITS_PRINCIPLES: ClassVar[dict[str, str]] = {
        "be_proactive": "Habit 1 — HealthMonitor heartbeats, daily briefs generated",
        "end_in_mind": "Habit 2 — every mission defines expected output + audit trail",
        "first_things_first": "Habit 3 — priority queues, importance-weighted memory",
        "think_win_win": "Habit 4 — memory consolidation benefits speed + depth",
        "seek_understand": "Habit 5 — search memory before responding, context first",
        "synergize": "Habit 6 — EventBus cross-component amplification",
        "sharpen_saw": "Habit 7 — LearningSkill consolidation, prune_memories()",
    }

    # Faraday Fortress layers
    FORTRESS_LAYERS: ClassVar[list[str]] = [
        "outer_wall",     # CSF 2.0 Govern
        "gatehouse",      # Bitwarden + MFA
        "courtyard",      # ITIL 4
        "armory",         # NIST 800-53
        "watchtowers",    # Grafana monitoring
        "infirmary",      # Oura + AAP guidelines
        "war_room",       # MITRE ATT&CK
        "vault",          # Backblaze backup
    ]

    # Doctrine-Lock rules
    DOCTRINE_LOCKS: ClassVar[list[str]] = [
        "zero_cloud_data",     # No raw data in cloud
        "local_first",         # Local storage default
        "privacy_first",       # Metadata-only collection
        "ethical_collection",  # Consent registry + kill switches
    ]

    def __init__(self) -> None:
        self._doctrine_loaded = False
        self._doctrine_hash = ""
        self._doctrine_text = ""

    def load_doctrine(self) -> bool:
        """Load the NCC Master Doctrine from disk."""
        if _DOCTRINE_PATH.exists():
            text = _DOCTRINE_PATH.read_text(encoding="utf-8")
            self._doctrine_text = text
            self._doctrine_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._doctrine_loaded = True
            logger.info("NCC Doctrine loaded, hash=%s", self._doctrine_hash)
            return True
        logger.warning("NCC Doctrine not found at %s", _DOCTRINE_PATH)
        return False

    @property
    def doctrine_loaded(self) -> bool:
        return self._doctrine_loaded

    @property
    def doctrine_hash(self) -> str:
        return self._doctrine_hash

    def score_pillar_art_of_war(self, context: dict[str, Any]) -> PillarScore:
        """Score Art of War compliance for a given operational context."""
        met: list[str] = []
        violated: list[str] = []

        # Check terrain awareness — are we routing based on data landscape?
        if context.get("adaptive_routing", False):
            met.append("terrain_awareness")
        else:
            violated.append("terrain_awareness")

        # Speed — are we dispatching within rate limits?
        if context.get("within_rate_limits", True):
            met.append("speed_decisive")
        else:
            violated.append("speed_decisive")

        # Win without fighting — proactive monitoring
        if context.get("proactive_briefs", False):
            met.append("win_without_fighting")
        else:
            violated.append("win_without_fighting")

        # Know thyself — memory analytics
        if context.get("memory_analytics", False):
            met.append("know_thyself")
        else:
            violated.append("know_thyself")

        # Deception defence — zero-trust
        if context.get("zero_trust_enabled", True):
            met.append("deception_defence")
        else:
            violated.append("deception_defence")

        # Prepare battlefield — golden task validation
        if context.get("golden_tasks_passing", True):
            met.append("prepare_battlefield")
        else:
            violated.append("prepare_battlefield")

        # Five factors
        if context.get("five_factors_applied", False):
            met.append("five_factors")
        else:
            violated.append("five_factors")

        total = len(self.ART_OF_WAR_PRINCIPLES)
        score = len(met) / total if total > 0 else 0.0
        return PillarScore("Art of War", round(score, 3), met, violated)

    def score_pillar_laws_of_power(self, context: dict[str, Any]) -> PillarScore:
        """Score 48 Laws of Power compliance."""
        met: list[str] = []
        violated: list[str] = []

        checks: dict[str, str] = {
            "policy_gate_active": "defer_to_master",
            "minimal_responses": "say_less",
            "audit_trails": "win_through_actions",
            "kill_switch_ready": "suspended_terror",
            "self_healing": "recreate_yourself",
            "retry_logic": "bold_action",
            "full_lifecycle": "plan_to_end",
            "rate_limiting": "master_timing",
            "graceful_degradation": "graceful_degradation",
            "auth_required": "earned_trust",
            "plugin_architecture": "formlessness",
        }

        for ctx_key, principle_key in checks.items():
            if context.get(ctx_key, False):
                met.append(principle_key)
            else:
                violated.append(principle_key)

        total = len(self.LAWS_OF_POWER_PRINCIPLES)
        score = len(met) / total if total > 0 else 0.0
        return PillarScore("48 Laws of Power", round(score, 3), met, violated)

    def score_pillar_seven_habits(self, context: dict[str, Any]) -> PillarScore:
        """Score 7 Habits compliance."""
        met: list[str] = []
        violated: list[str] = []

        checks: dict[str, str] = {
            "health_monitor_active": "be_proactive",
            "mission_output_defined": "end_in_mind",
            "priority_queues": "first_things_first",
            "memory_consolidation": "think_win_win",
            "context_first_search": "seek_understand",
            "event_bus_active": "synergize",
            "learning_engine_active": "sharpen_saw",
        }

        for ctx_key, principle_key in checks.items():
            if context.get(ctx_key, False):
                met.append(principle_key)
            else:
                violated.append(principle_key)

        total = len(self.SEVEN_HABITS_PRINCIPLES)
        score = len(met) / total if total > 0 else 0.0
        return PillarScore("7 Habits", round(score, 3), met, violated)

    def check_doctrine(self, context: dict[str, Any]) -> DoctrineCheckResult:
        """Full doctrine compliance check across all pillars and layers."""
        p1 = self.score_pillar_art_of_war(context)
        p2 = self.score_pillar_laws_of_power(context)
        p3 = self.score_pillar_seven_habits(context)

        # Fortress layer checks
        fortress_ok: list[str] = []
        fortress_warn: list[str] = []
        for layer in self.FORTRESS_LAYERS:
            if context.get(f"fortress_{layer}", False):
                fortress_ok.append(layer)
            else:
                fortress_warn.append(layer)

        # Doctrine-Lock checks
        lock_violations: list[str] = []
        if context.get("cloud_data_present", False):
            lock_violations.append("zero_cloud_data")
        if not context.get("local_first", True):
            lock_violations.append("local_first")
        if context.get("raw_content_captured", False):
            lock_violations.append("privacy_first")
        if not context.get("consent_registry", True):
            lock_violations.append("ethical_collection")

        # Resonance = average of pillar scores x fortress coverage
        pillar_avg = (p1.score + p2.score + p3.score) / 3
        fortress_ratio = len(fortress_ok) / len(self.FORTRESS_LAYERS) if self.FORTRESS_LAYERS else 1.0
        lock_penalty = 1.0 - (len(lock_violations) * 0.25)
        resonance = round(pillar_avg * fortress_ratio * max(lock_penalty, 0.0), 4)

        compliant = len(lock_violations) == 0 and resonance >= 0.5
        return DoctrineCheckResult(
            compliant=compliant,
            pillar_scores=[p1, p2, p3],
            fortress_layers_ok=fortress_ok,
            fortress_layers_warn=fortress_warn,
            doctrine_lock_violations=lock_violations,
            resonance_score=resonance,
        )

    def run_pdca_audit(self, phase: str, metrics: dict[str, Any]) -> PDCAAudit:
        """Run a PDCA audit for the given phase."""
        findings: list[str] = []
        recommendations: list[str] = []
        score = 0.0

        if phase == "plan":
            if metrics.get("insights_queued", 0) > 0:
                findings.append(f"insights_queued={metrics['insights_queued']}")
                score += 0.25
            if metrics.get("missions_planned", 0) > 0:
                findings.append(f"missions_planned={metrics['missions_planned']}")
                score += 0.25
            if metrics.get("risk_assessed", False):
                findings.append("risk_assessment_complete")
                score += 0.25
            if metrics.get("resources_allocated", False):
                findings.append("resources_allocated")
                score += 0.25
            if score < 0.5:
                recommendations.append("Increase planning depth — add risk assessment")

        elif phase == "do":
            executed = metrics.get("missions_executed", 0)
            if executed > 0:
                findings.append(f"missions_executed={executed}")
                score += 0.5
            success_rate = metrics.get("success_rate", 0.0)
            findings.append(f"success_rate={success_rate:.1%}")
            score += success_rate * 0.5
            if success_rate < 0.8:
                recommendations.append("Improve execution reliability — review failure modes")

        elif phase == "check":
            if metrics.get("audit_complete", False):
                findings.append("audit_complete")
                score += 0.5
            if metrics.get("metrics_reviewed", False):
                findings.append("metrics_reviewed")
                score += 0.25
            if metrics.get("anomalies_flagged", False):
                findings.append("anomalies_flagged")
                score += 0.25
            if score < 0.75:
                recommendations.append("Deepen audit — review all metrics systematically")

        elif phase == "act":
            if metrics.get("improvements_applied", 0) > 0:
                findings.append(f"improvements_applied={metrics['improvements_applied']}")
                score += 0.5
            if metrics.get("release_notes", False):
                findings.append("release_notes_published")
                score += 0.25
            if metrics.get("doctrine_updated", False):
                findings.append("doctrine_updated")
                score += 0.25
            if score < 0.5:
                recommendations.append("Close the loop — apply improvements and publish notes")

        return PDCAAudit(phase=phase, findings=findings, score=round(score, 3), recommendations=recommendations)

    def summary(self) -> dict[str, Any]:
        """Return connector summary."""
        return {
            "status": "loaded" if self._doctrine_loaded else "disconnected",
            "doctrine_hash": self._doctrine_hash,
            "doctrine_path": str(_DOCTRINE_PATH),
            "pillars": ["Art of War", "48 Laws of Power", "7 Habits"],
            "fortress_layers": len(self.FORTRESS_LAYERS),
            "doctrine_locks": len(self.DOCTRINE_LOCKS),
        }


# ── AAC Asset Bridge ──────────────────────────────────────────


@dataclass
class PortfolioSnapshot:
    """Snapshot of the AAC portfolio state."""

    connected: bool = False
    exchange_count: int = 0
    exchanges: list[str] = field(default_factory=list)
    strategy_count: int = 0
    agent_count: int = 0
    total_positions: int = 0
    health: str = "unknown"


@dataclass
class StrategyReport:
    """Performance report for AAC strategies."""

    strategy_count: int = 0
    active_strategies: list[str] = field(default_factory=list)
    performance_summary: dict[str, float] = field(default_factory=dict)


@dataclass
class TradingSignal:
    """Trading signal relayed from AAC to the council."""

    signal_type: str = ""  # buy | sell | hold | rebalance
    source_strategy: str = ""
    confidence: float = 0.0
    asset: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AACAssetBridge:
    """Connects the council to the Autonomous Asset Collective.

    Discovers AAC at the known path and provides:
    - Portfolio snapshot retrieval
    - Strategy performance summaries
    - Trading signal relay
    - Exchange connector status
    """

    # Known AAC installation path
    AAC_ROOT: ClassVar[pathlib.Path] = pathlib.Path("C:/dev/AAC_fresh")

    # Known exchange connectors in AAC v2.7.0
    KNOWN_EXCHANGES: ClassVar[list[str]] = [
        "binance", "coinbase", "kraken", "ibkr",
        "ndax", "moomoo", "noxirise", "metalx",
    ]

    def __init__(self, aac_root: pathlib.Path | None = None) -> None:
        self._root = aac_root or self.AAC_ROOT
        self._connected = False
        self._version = ""

    def discover(self) -> bool:
        """Discover AAC installation and check connectivity."""
        if self._root.exists() and self._root.is_dir():
            self._connected = True
            # Try to detect version from common locations
            for vfile in ["VERSION", "version.txt", "pyproject.toml"]:
                vpath = self._root / vfile
                if vpath.exists():
                    text = vpath.read_text(encoding="utf-8")
                    match = re.search(r"(\d+\.\d+\.\d+)", text)
                    if match:
                        self._version = match.group(1)
                        break
            if not self._version:
                self._version = "unknown"
            logger.info("AAC discovered at %s (v%s)", self._root, self._version)
            return True
        logger.warning("AAC not found at %s", self._root)
        return False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def version(self) -> str:
        return self._version

    def _check_exchange_dirs(self) -> list[str]:
        """Check which exchange connectors exist in AAC."""
        found: list[str] = []
        for exchange in self.KNOWN_EXCHANGES:
            # Check common directory patterns
            for pattern in [
                self._root / "exchanges" / exchange,
                self._root / "src" / "exchanges" / exchange,
                self._root / "connectors" / exchange,
            ]:
                if pattern.exists():
                    found.append(exchange)
                    break
        return found

    def portfolio_snapshot(self) -> PortfolioSnapshot:
        """Get a snapshot of the current portfolio state."""
        if not self._connected:
            return PortfolioSnapshot(connected=False, health="disconnected")

        exchanges = self._check_exchange_dirs()

        # Check for strategy directories
        strategy_count = 0
        for sdir in ["strategies", "src/strategies"]:
            spath = self._root / sdir
            if spath.exists():
                strategy_count = sum(1 for f in spath.rglob("*.py") if not f.name.startswith("_"))
                break

        return PortfolioSnapshot(
            connected=True,
            exchange_count=len(exchanges),
            exchanges=exchanges,
            strategy_count=strategy_count,
            agent_count=0,  # Would require deeper AAC introspection
            total_positions=0,  # Would require live AAC connection
            health="discovered",
        )

    def strategy_report(self) -> StrategyReport:
        """Get a strategy performance report."""
        if not self._connected:
            return StrategyReport()

        strategies: list[str] = []
        for sdir in ["strategies", "src/strategies"]:
            spath = self._root / sdir
            if spath.exists():
                strategies = [
                    f.stem for f in spath.rglob("*.py")
                    if not f.name.startswith("_")
                ]
                break

        return StrategyReport(
            strategy_count=len(strategies),
            active_strategies=strategies[:20],  # Cap list size
        )

    def relay_signal(self, signal: TradingSignal) -> dict[str, Any]:
        """Relay a trading signal from AAC to the council for analysis."""
        if not self._connected:
            return {"status": "relay_failed", "reason": "aac_disconnected"}

        return {
            "status": "signal_relayed",
            "signal_type": signal.signal_type,
            "source_strategy": signal.source_strategy,
            "confidence": signal.confidence,
            "asset": signal.asset,
        }

    def summary(self) -> dict[str, Any]:
        """Return bridge summary."""
        return {
            "status": "connected" if self._connected else "disconnected",
            "root": str(self._root),
            "version": self._version,
            "known_exchanges": len(self.KNOWN_EXCHANGES),
        }


# ── BRS Orchestrator ──────────────────────────────────────────


@dataclass
class AgencyDispatch:
    """Dispatch request to BRS (Bit Rage Systems)."""

    workflow_id: str = ""
    target_agents: list[str] = field(default_factory=list)
    task_description: str = ""
    priority: str = "normal"  # low | normal | high | critical
    rbac_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowStatus:
    """Status of a BRS workflow."""

    workflow_id: str = ""
    state: str = "unknown"  # pending | running | completed | failed
    agents_involved: list[str] = field(default_factory=list)
    progress_pct: float = 0.0
    result: dict[str, Any] = field(default_factory=dict)



class BRSOrchestrator:
    """Connects the council to BRS (Bit Rage Systems).

    Discovers BRS at the known path and provides:
    - Multi-agent dispatch relay
    - RBAC policy coordination
    - Workflow composition
    - Capability bridging
    """

    # Known BRS installation path (Digital-Labour)
    SA_ROOT: ClassVar[pathlib.Path] = pathlib.Path("C:/dev/Digital-Labour")

    def __init__(self, sa_root: pathlib.Path | None = None) -> None:
        self._root = sa_root or self.SA_ROOT
        self._connected = False
        self._capabilities: list[str] = []

    def discover(self) -> bool:
        """Discover BRS installation."""
        if self._root.exists() and self._root.is_dir():
            self._connected = True
            # Scan for capability modules
            self._capabilities = self._scan_capabilities()
            logger.info(
                "BRS discovered at %s (%d capabilities)",
                self._root,
                len(self._capabilities),
            )
            return True
        logger.warning("BRS not found at %s", self._root)
        return False

    def _scan_capabilities(self) -> list[str]:
        """Scan BRS for available capabilities."""
        caps: list[str] = []
        for cap_dir in ["agents", "skills", "workflows", "tools"]:
            cpath = self._root / cap_dir
            if cpath.exists():
                caps.append(cap_dir)
        return caps

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def capabilities(self) -> list[str]:
        return list(self._capabilities)

    def dispatch(self, request: AgencyDispatch) -> dict[str, Any]:
        """Dispatch a workflow request to BRS."""
        if not self._connected:
            return {"status": "dispatch_failed", "reason": "agency_disconnected"}

        return {
            "status": "dispatched",
            "workflow_id": request.workflow_id,
            "target_agents": request.target_agents,
            "priority": request.priority,
            "capabilities_available": self._capabilities,
        }

    def check_workflow(self, workflow_id: str) -> WorkflowStatus:
        """Check status of a running workflow."""
        if not self._connected:
            return WorkflowStatus(workflow_id=workflow_id, state="disconnected")

        return WorkflowStatus(
            workflow_id=workflow_id,
            state="pending",
            agents_involved=[],
            progress_pct=0.0,
        )

    def rbac_check(self, agent_codename: str, action: str) -> dict[str, Any]:
        """Check RBAC permissions for an agent action."""
        if not self._connected:
            return {"allowed": False, "reason": "agency_disconnected"}

        # Default: allow all council agents (they operate within NCL's trust boundary)
        return {
            "allowed": True,
            "agent": agent_codename,
            "action": action,
            "policy": "council_trusted",
        }

    def summary(self) -> dict[str, Any]:
        """Return orchestrator summary."""
        return {
            "status": "connected" if self._connected else "disconnected",
            "root": str(self._root),
            "capabilities": self._capabilities,
            "capability_count": len(self._capabilities),
        }


# Backward-compatible alias
SuperAgencyOrchestrator = BRSOrchestrator


# ── Resonance Triad Engine ────────────────────────────────────


class ResonanceTriad:
    """Unified engine computing resonance energy across the three pillars.

    RESONANCE ENERGY = NCC (Governance) x BRS (Execution) x AAC (Assets)

    The triad amplifies capabilities when all three systems are
    connected and healthy. Degradation in any pillar reduces the
    overall resonance proportionally.
    """

    def __init__(
        self,
        ncc: NCCGovernanceConnector | None = None,
        aac: AACAssetBridge | None = None,
        agency: BRSOrchestrator | None = None,
    ) -> None:
        self.ncc = ncc or NCCGovernanceConnector()
        self.aac = aac or AACAssetBridge()
        self.agency = agency or BRSOrchestrator()

    def initialize(self) -> dict[str, bool]:
        """Initialize all three pillars."""
        ncc_ok = self.ncc.load_doctrine()
        aac_ok = self.aac.discover()
        agency_ok = self.agency.discover()
        return {
            "ncc": ncc_ok,
            "aac": aac_ok,
            "agency": agency_ok,
        }

    def compute_resonance(self, context: dict[str, Any]) -> dict[str, Any]:
        """Compute the resonance energy across all three pillars.

        Returns a score from 0.0 to 1.0 where:
        - 1.0 = all three pillars fully connected and compliant
        - 0.0 = complete disconnection
        """
        # NCC score from doctrine check
        ncc_score = 0.0
        doctrine_result: DoctrineCheckResult | None = None
        if self.ncc.doctrine_loaded:
            doctrine_result = self.ncc.check_doctrine(context)
            ncc_score = doctrine_result.resonance_score

        # AAC score from connectivity
        aac_score = 0.0
        if self.aac.connected:
            snapshot = self.aac.portfolio_snapshot()
            # Score based on exchange coverage and strategy count
            exchange_ratio = snapshot.exchange_count / len(AACAssetBridge.KNOWN_EXCHANGES) if AACAssetBridge.KNOWN_EXCHANGES else 0.0
            strategy_ratio = min(snapshot.strategy_count / 52, 1.0)
            aac_score = round((exchange_ratio + strategy_ratio) / 2, 4)

        # Agency score from capabilities
        agency_score = 0.0
        if self.agency.connected:
            cap_count = len(self.agency.capabilities)
            agency_score = round(min(cap_count / 4, 1.0), 4)

        # Resonance = geometric mean of all three pillars
        # If any pillar is 0, add a base connectivity score
        pillar_scores = [
            max(ncc_score, 0.1 if self.ncc.doctrine_loaded else 0.0),
            max(aac_score, 0.1 if self.aac.connected else 0.0),
            max(agency_score, 0.1 if self.agency.connected else 0.0),
        ]

        # Geometric mean for multiplicative resonance
        product = pillar_scores[0] * pillar_scores[1] * pillar_scores[2]
        resonance = round(product ** (1 / 3), 4) if product > 0 else 0.0

        return {
            "resonance_energy": resonance,
            "ncc_score": ncc_score,
            "aac_score": aac_score,
            "agency_score": agency_score,
            "pillars_connected": sum(1 for s in pillar_scores if s > 0),
            "doctrine_compliant": doctrine_result.compliant if doctrine_result else False,
        }

    def health(self) -> dict[str, Any]:
        """Full triad health check."""
        return {
            "ncc": self.ncc.summary(),
            "aac": self.aac.summary(),
            "agency": self.agency.summary(),
            "pillars_active": sum([
                self.ncc.doctrine_loaded,
                self.aac.connected,
                self.agency.connected,
            ]),
            "total_pillars": 3,
        }

    def full_report(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate a comprehensive triad report."""
        resonance = self.compute_resonance(context)
        health = self.health()

        # PDCA snapshot
        pdca_plan = self.ncc.run_pdca_audit("plan", context)
        pdca_do = self.ncc.run_pdca_audit("do", context)

        return {
            "resonance": resonance,
            "health": health,
            "pdca": {
                "plan": {"score": pdca_plan.score, "findings": pdca_plan.findings},
                "do": {"score": pdca_do.score, "findings": pdca_do.findings},
            },
            "triad_formula": "RESONANCE = NCC(Governance) x BRS(Execution) x AAC(Assets)",
        }
