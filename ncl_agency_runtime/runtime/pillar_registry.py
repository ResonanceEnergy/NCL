#!/usr/bin/env python3
"""
NCC Pillar Registry — Canonical registry of all Resonance Energy pillars.
═══════════════════════════════════════════════════════════════════════════
NCC = Natrix Command & Control — supreme governance over all pillars.

The Triad:
    NCL  (Brain)   — Cognitive augmentation, second brain, memory
    AAC  (Bank)    — Algorithmic Asset Command, trading, portfolio
    BRS  (Systems) — Bit Rage Systems — agent workforce + autonomous workers

Each pillar registers its capabilities, health endpoint, and message contract.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

LOG = logging.getLogger("ncc.pillar_registry")


# ═══════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════

class PillarID(StrEnum):
    """Canonical pillar identifiers."""
    NCC = "ncc"               # Natrix Command & Control (governance root)
    NCL = "ncl"               # Brain — cognitive augmentation
    AAC = "aac"               # Bank — algorithmic asset command
    BRS = "brs"               # Bit Rage Systems — agent workforce + autonomous workers


class PillarStatus(StrEnum):
    """Operational status of a pillar."""
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    BOOTSTRAPPING = "bootstrapping"


class CapabilityType(StrEnum):
    """Types of capabilities a pillar can advertise."""
    MEMORY = "memory"
    TRADING = "trading"
    RESEARCH = "research"
    TASK_EXECUTION = "task_execution"
    DATA_INGESTION = "data_ingestion"
    REPORT_GENERATION = "report_generation"
    AGENT_ORCHESTRATION = "agent_orchestration"
    GOVERNANCE = "governance"
    LEARNING = "learning"
    RISK_MANAGEMENT = "risk_management"
    PORTFOLIO = "portfolio"
    SIGNAL_PROCESSING = "signal_processing"
    BIT_RAGE_SYSTEMS = "bit_rage_systems"
    CONTENT_CREATION = "content_creation"


# ═══════════════════════════════════════════════════════════════
#  Data Structures
# ═══════════════════════════════════════════════════════════════

@dataclass
class Capability:
    """A capability advertised by a pillar."""
    name: str
    cap_type: CapabilityType
    version: str = "1.0.0"
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cap_type"] = self.cap_type.value
        return d


@dataclass
class PillarRegistration:
    """Registration record for a pillar in the NCC registry."""
    pillar_id: PillarID
    name: str
    role: str                                      # Brain / Bank / Agency / Labour
    description: str = ""
    status: PillarStatus = PillarStatus.OFFLINE
    capabilities: list[Capability] = field(default_factory=list)
    endpoint: str = ""                             # local URI or module path
    version: str = "1.0.0"
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_heartbeat: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pillar_id"] = self.pillar_id.value
        d["status"] = self.status.value
        d["capabilities"] = [c.to_dict() if isinstance(c, Capability) else c for c in self.capabilities]
        return d


# ═══════════════════════════════════════════════════════════════
#  Pillar Registry Singleton
# ═══════════════════════════════════════════════════════════════

class PillarRegistry:
    """Central registry where all pillars register and discover each other.

    Art of War: "Know yourself, know your enemy — 100 battles, 100 victories."
    Every pillar must be known; every capability must be discoverable.
    Habit 6 (Synergize): The triad is greater than the sum of its parts.
    """

    _instance: ClassVar[PillarRegistry | None] = None

    def __init__(self) -> None:
        self._pillars: dict[PillarID, PillarRegistration] = {}
        self._capability_index: dict[CapabilityType, list[PillarID]] = {}
        self._boot_time = time.time()

    @classmethod
    def get_instance(cls) -> PillarRegistry:
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    # ── Registration ──────────────────────────────────────────

    def register(self, reg: PillarRegistration) -> None:
        """Register or update a pillar."""
        self._pillars[reg.pillar_id] = reg
        for cap in reg.capabilities:
            ct = cap.cap_type if isinstance(cap.cap_type, CapabilityType) else CapabilityType(cap.cap_type)
            self._capability_index.setdefault(ct, [])
            if reg.pillar_id not in self._capability_index[ct]:
                self._capability_index[ct].append(reg.pillar_id)
        LOG.info("Pillar registered: %s (%s) — %s", reg.pillar_id.value, reg.name, reg.status.value)

    def deregister(self, pillar_id: PillarID) -> bool:
        """Remove a pillar from the registry."""
        if pillar_id in self._pillars:
            del self._pillars[pillar_id]
            for cap_list in self._capability_index.values():
                if pillar_id in cap_list:
                    cap_list.remove(pillar_id)
            LOG.info("Pillar deregistered: %s", pillar_id.value)
            return True
        return False

    # ── Discovery ─────────────────────────────────────────────

    def get(self, pillar_id: PillarID) -> PillarRegistration | None:
        """Look up a pillar by ID."""
        return self._pillars.get(pillar_id)

    def list_pillars(self) -> list[PillarRegistration]:
        """Return all registered pillars."""
        return list(self._pillars.values())

    def find_by_capability(self, cap_type: CapabilityType) -> list[PillarRegistration]:
        """Find all pillars advertising a given capability type."""
        ids = self._capability_index.get(cap_type, [])
        return [self._pillars[pid] for pid in ids if pid in self._pillars]

    def find_online(self) -> list[PillarRegistration]:
        """Return only pillars with ONLINE status."""
        return [p for p in self._pillars.values() if p.status == PillarStatus.ONLINE]

    # ── Health ────────────────────────────────────────────────

    def heartbeat(self, pillar_id: PillarID) -> bool:
        """Record a heartbeat from a pillar."""
        reg = self._pillars.get(pillar_id)
        if not reg:
            return False
        reg.last_heartbeat = datetime.now(UTC).isoformat()
        if reg.status == PillarStatus.BOOTSTRAPPING:
            reg.status = PillarStatus.ONLINE
        return True

    def set_status(self, pillar_id: PillarID, status: PillarStatus) -> bool:
        """Update pillar status."""
        reg = self._pillars.get(pillar_id)
        if not reg:
            return False
        old = reg.status
        reg.status = status
        LOG.info("Pillar %s: %s → %s", pillar_id.value, old.value, status.value)
        return True

    def health_summary(self) -> dict[str, Any]:
        """Produce a health summary for NCC governance dashboards."""
        summary: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_s": round(time.time() - self._boot_time, 1),
            "total_pillars": len(self._pillars),
            "online": 0,
            "degraded": 0,
            "offline": 0,
            "pillars": {},
        }
        for pid, reg in self._pillars.items():
            summary["pillars"][pid.value] = {
                "name": reg.name,
                "role": reg.role,
                "status": reg.status.value,
                "capabilities": len(reg.capabilities),
                "last_heartbeat": reg.last_heartbeat,
            }
            if reg.status == PillarStatus.ONLINE:
                summary["online"] += 1
            elif reg.status == PillarStatus.DEGRADED:
                summary["degraded"] += 1
            else:
                summary["offline"] += 1
        return summary

    # ── Triad Check ───────────────────────────────────────────

    def triad_online(self) -> bool:
        """Check if the core triad (NCL + AAC + SA) is all ONLINE."""
        for pid in (PillarID.NCL, PillarID.AAC, PillarID.BRS):
            reg = self._pillars.get(pid)
            if not reg or reg.status != PillarStatus.ONLINE:
                return False
        return True

    def triad_status(self) -> dict[str, str]:
        """Concise triad status."""
        result: dict[str, str] = {}
        for pid in (PillarID.NCL, PillarID.AAC, PillarID.BRS):
            reg = self._pillars.get(pid)
            result[pid.value] = reg.status.value if reg else "unregistered"
        return result


# ═══════════════════════════════════════════════════════════════
#  Built-in Pillar Definitions (default registrations)
# ═══════════════════════════════════════════════════════════════

def _ncl_registration() -> PillarRegistration:
    """NCL — The Brain."""
    return PillarRegistration(
        pillar_id=PillarID.NCL,
        name="NUREALCORTEXLINK",
        role="Brain",
        description="Cognitive augmentation, second brain, memory, learning engine, event processing",
        capabilities=[
            Capability("memory_store", CapabilityType.MEMORY, description="Store episodic/semantic/working memories"),
            Capability("memory_search", CapabilityType.MEMORY, description="Semantic search across memory tiers"),
            Capability("event_ingestion", CapabilityType.DATA_INGESTION, description="iPhone/Shortcuts event relay"),
            Capability("learning_engine", CapabilityType.LEARNING, description="Pattern extraction and synthesis"),
            Capability("daily_brief", CapabilityType.REPORT_GENERATION, description="Cognitive state daily brief"),
            Capability("doctrine_retrieval", CapabilityType.RESEARCH, description="NCC Doctrine knowledge base"),
        ],
        endpoint="ncl_agency_runtime.agents.super_openclaw_agent",
        version="3.0.0",
        status=PillarStatus.BOOTSTRAPPING,
    )


def _aac_registration() -> PillarRegistration:
    """AAC — The Bank."""
    return PillarRegistration(
        pillar_id=PillarID.AAC,
        name="Algorithmic Asset Command",
        role="Bank",
        description="Trading systems, portfolio management, 8 exchange connectors, 52 strategies",
        capabilities=[
            Capability("trading_execution", CapabilityType.TRADING, description="Execute trades across 8 exchanges"),
            Capability("portfolio_tracking", CapabilityType.PORTFOLIO, description="Real-time portfolio monitoring"),
            Capability("risk_management", CapabilityType.RISK_MANAGEMENT, description="Position sizing, stop-losses, exposure limits"),
            Capability("signal_processing", CapabilityType.SIGNAL_PROCESSING, description="Market signal analysis, 52 strategies"),
            Capability("backtest_engine", CapabilityType.RESEARCH, description="Historical strategy backtesting"),
            Capability("entropy_regime", CapabilityType.RISK_MANAGEMENT, description="E1-E5 market entropy classification"),
        ],
        endpoint="aac",
        version="2.7.0",
        status=PillarStatus.BOOTSTRAPPING,
    )


def _brs_registration() -> PillarRegistration:
    """Bit Rage Systems — Merged Agency + Digital Labour."""
    return PillarRegistration(
        pillar_id=PillarID.BRS,
        name="Bit Rage Systems",
        role="Systems",
        description="Agent workforce orchestration, autonomous workers, task routing, digital labour",
        capabilities=[
            Capability("agent_dispatch", CapabilityType.AGENT_ORCHESTRATION, description="Route tasks to specialised agents"),
            Capability("task_management", CapabilityType.TASK_EXECUTION, description="Track and manage task lifecycle"),
            Capability("research_cell", CapabilityType.RESEARCH, description="Research pattern gathering"),
            Capability("synthesis_cell", CapabilityType.RESEARCH, description="Merge and synthesise findings"),
            Capability("governance_cell", CapabilityType.GOVERNANCE, description="Apply gates and enforce evidence labels"),
            Capability("entropy_sentinel", CapabilityType.GOVERNANCE, description="Detect drift, coupling, rework"),
            Capability("content_creation", CapabilityType.CONTENT_CREATION, description="Generate reports, briefs, documents"),
            Capability("data_processing", CapabilityType.DATA_INGESTION, description="ETL, transformation, enrichment"),
            Capability("automated_research", CapabilityType.RESEARCH, description="Web scraping, API polling, data gathering"),
            Capability("task_execution", CapabilityType.BIT_RAGE_SYSTEMS, description="Execute queued work items autonomously"),
            Capability("report_generation", CapabilityType.REPORT_GENERATION, description="Compile cross-pillar reports"),
        ],
        endpoint="bit_rage_systems",
        version="1.0.0",
        status=PillarStatus.BOOTSTRAPPING,
    )


def _ncc_registration() -> PillarRegistration:
    """NCC — The Governance Root."""
    return PillarRegistration(
        pillar_id=PillarID.NCC,
        name="Natrix Command & Control",
        role="Governance",
        description="Supreme governance over all Resonance Energy pillars — the triad orchestrator",
        capabilities=[
            Capability("governance", CapabilityType.GOVERNANCE, description="PDCA loop, audit, doctrine enforcement"),
            Capability("orchestration", CapabilityType.AGENT_ORCHESTRATION, description="Cross-pillar task coordination"),
        ],
        endpoint="ncc",
        version="1.0.0",
        status=PillarStatus.BOOTSTRAPPING,
    )


def bootstrap_registry() -> PillarRegistry:
    """Create and populate the registry with all default pillar registrations."""
    registry = PillarRegistry.get_instance()
    for factory in (_ncc_registration, _ncl_registration, _aac_registration,
                    _brs_registration):
        registry.register(factory())
    return registry
