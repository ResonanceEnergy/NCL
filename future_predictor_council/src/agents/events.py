"""Event schema and contracts for the real-time event system.

All events flow through the EventRouter to ATLAS Mission Control.
Every event is typed, traceable, cost-aware, and privacy-tagged.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """Top-level event classification."""

    # Core flows
    INTENT_USER = "intent.user"         # Natural-language goal, approval, constraint
    INTENT_SYSTEM = "intent.system"     # Automated trigger (schedule, threshold)
    DATA_UPDATE = "data.update"         # Dataset/feature refresh notice
    MODEL_CYCLE = "model.cycle"         # Forecast results, XAI dossier ready
    ACTION_RESULT = "action.result"     # Writeback/deploy outcome
    POLICY_CHANGE = "policy.change"     # ReleasePolicy edit, freeze, thaw

    # Telemetry
    TELEMETRY_AGENT = "telemetry.agent"     # Agent outcomes, errors, latencies
    TELEMETRY_SYSTEM = "telemetry.system"   # System health, resource usage
    TELEMETRY_COST = "telemetry.cost"       # Spend tracking

    # Safety
    SECURITY_ALERT = "security.alert"       # Vulnerability, breach attempt
    SECURITY_AUDIT = "security.audit"       # Audit trail entry

    # Agent-to-agent
    AGENT_REQUEST = "agent.request"         # One agent asks another for work
    AGENT_RESPONSE = "agent.response"       # Response from downstream agent

    # Wolfram Physics
    WOLFRAM_BRANCH = "wolfram.branch"              # New multiway prediction branch
    WOLFRAM_MERGE = "wolfram.merge"                # Two branches converged
    WOLFRAM_IRREDUCIBILITY = "wolfram.irreducibility"  # CI detection result
    WOLFRAM_OBSERVE = "wolfram.observe"            # Observer projection event

    # Resonance Triad: NCC x Super Agency x AAC
    NCC_DOCTRINE_CHECK = "ncc.doctrine_check"      # Doctrine compliance result
    NCC_PILLAR_SCORE = "ncc.pillar_score"          # Three Pillars scoring event
    NCC_PDCA_AUDIT = "ncc.pdca_audit"              # PDCA audit loop result
    AAC_PORTFOLIO_SYNC = "aac.portfolio_sync"      # Portfolio snapshot from AAC
    AAC_SIGNAL_RELAY = "aac.signal_relay"           # Trading signal relayed
    AAC_STRATEGY_REPORT = "aac.strategy_report"    # Strategy performance report
    AGENCY_DISPATCH = "agency.dispatch"             # Workflow dispatched to Super Agency
    AGENCY_WORKFLOW = "agency.workflow"             # Workflow status update
    AGENCY_GOVERNANCE = "agency.governance"         # RBAC / governance check
    TRIAD_RESONANCE = "triad.resonance"            # Resonance energy computation

    # Unit 8200 Intelligence Doctrine
    SIGINT_COLLECTION = "sigint.collection"         # Intelligence collection event
    SIGINT_FUSION = "sigint.fusion"                 # Multi-source fusion result
    SIGINT_ANOMALY = "sigint.anomaly"               # Anomaly / pattern detected
    SIGINT_DISSEMINATION = "sigint.dissemination"   # Intelligence shared (compartmented)
    REDTEAM_PROBE = "redteam.probe"                 # Red team adversarial test
    REDTEAM_FINDING = "redteam.finding"             # Vulnerability discovered
    BLUETEAM_DEFENSE = "blueteam.defense"           # Blue team defensive action
    UNIT8200_DOCTRINE = "unit8200.doctrine"         # Overall doctrine compliance

    # Geopolitical Advisor — Jiang Xueqin Framework
    GEOPOL_SIGNAL = "geopol.signal"                 # Geopolitical signal ingested
    GEOPOL_ASSESSMENT = "geopol.assessment"         # Strategic assessment result
    GEOPOL_NARRATIVE = "geopol.narrative"           # Narrative engine output
    GEOPOL_PIPELINE = "geopol.pipeline"             # Pipeline cycle status
    GEOPOL_ADVISORY = "geopol.advisory"             # Advisory note issued

    # Second Brain — Tiago Forte Knowledge Engine
    BRAIN_CAPTURE = "brain.capture"                 # Knowledge captured (CODE stage 1)
    BRAIN_ORGANIZE = "brain.organize"               # Knowledge organized into PARA
    BRAIN_DISTILL = "brain.distill"                 # Progressive summarization applied
    BRAIN_EXPRESS = "brain.express"                 # Knowledge expressed / published
    BRAIN_RETRIEVE = "brain.retrieve"               # Just-In-Time retrieval executed
    BRAIN_CYCLE = "brain.cycle"                     # Maintenance cycle completed

    # AI Daily Brief — NLW + Peter H. Diamandis Intelligence
    BRIEF_INGEST = "brief.ingest"                   # AI briefing signal ingested
    BRIEF_ANALYZE = "brief.analyze"                 # Briefing analysis produced
    BRIEF_EXPONENTIAL = "brief.exponential"         # Exponential signal tracked (6 D's)
    BRIEF_CONVERGE = "brief.converge"               # Technology convergence detected
    BRIEF_DIGEST = "brief.digest"                   # Daily digest generated
    BRIEF_CYCLE = "brief.cycle"                     # Full pipeline cycle completed

    # X (Twitter) Intelligence — Feed, Likes & Reposts Pipeline
    X_FEED_INGEST = "xfeed.ingest"                  # X post ingested from feed/likes/reposts
    X_FEED_CLASSIFY = "xfeed.classify"              # Post classified by domain & urgency
    X_FEED_FILTER = "xfeed.filter"                  # Post quality-filtered
    X_FEED_ROUTE = "xfeed.route"                    # Post routed to target agent/division
    X_FEED_DIGEST = "xfeed.digest"                  # Feed digest generated
    X_FEED_CYCLE = "xfeed.cycle"                    # Full pipeline cycle completed

    # YouTube Intelligence — "There Is An AI For That" Pipeline
    YT_INGEST = "yt.ingest"                          # Video entry ingested
    YT_EXTRACT = "yt.extract"                        # Tool mentions extracted
    YT_CLASSIFY = "yt.classify"                      # Video classified by category & impact
    YT_FILTER = "yt.filter"                          # Video impact-filtered
    YT_ROUTE = "yt.route"                            # Video routed to target agent/division
    YT_TREND = "yt.trend"                            # Trend report generated
    YT_CYCLE = "yt.cycle"                            # Full pipeline cycle completed

    # AI Upload Intelligence — Strategic AI News & Analysis Pipeline
    AU_INGEST = "au.ingest"                          # AI Upload video ingested
    AU_ANALYZE = "au.analyze"                        # Content analysis performed
    AU_SIGNAL = "au.signal"                          # Strategic signal extracted
    AU_ENTITY = "au.entity"                          # Entity mention catalogued
    AU_NARRATIVE = "au.narrative"                    # Narrative thread tracked
    AU_BRIEF = "au.brief"                            # Intelligence brief generated


class PrivacyLevel(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass
class PrivacyTag:
    pii: bool = False
    level: PrivacyLevel = PrivacyLevel.INTERNAL
    policy_tags: list[str] = field(default_factory=lambda: ["internal"])


@dataclass
class CostTag:
    gpu_minutes: float = 0.0
    cpu_minutes: float = 0.0
    usd: float = 0.0


@dataclass
class Event:
    """Core event contract — every signal in the system is an Event."""

    detail_type: EventType | str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""                    # e.g. "agent.ORACLE", "user", "scheduler"
    subject: str = ""                   # e.g. "forecast:v1:sku_1234"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)
    severity: str = "info"
    tenant: str = "default"
    privacy: PrivacyTag = field(default_factory=PrivacyTag)
    cost: CostTag = field(default_factory=CostTag)
    parent_id: str | None = None        # For chaining events

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "ts": self.ts,
            "source": self.source,
            "detail_type": self.detail_type.value if isinstance(self.detail_type, EventType) else self.detail_type,
            "subject": self.subject,
            "tenant": self.tenant,
            "severity": self.severity,
            "privacy": {
                "pii": self.privacy.pii,
                "level": self.privacy.level.value,
                "policy_tags": self.privacy.policy_tags,
            },
            "cost": {
                "gpu_minutes": self.cost.gpu_minutes,
                "cpu_minutes": self.cost.cpu_minutes,
                "usd": self.cost.usd,
            },
            "payload": self.payload,
            "parent_id": self.parent_id,
        }


# ── Helpers ─────────────────────────────────────────────────────
def make_intent(goal: str, **kwargs: Any) -> Event:
    """Create a user intent event."""
    return Event(
        detail_type=EventType.INTENT_USER,
        source="user",
        payload={"goal": goal, **kwargs},
    )


def make_data_update(dataset: str, rows: int = 0, **kwargs: Any) -> Event:
    return Event(
        detail_type=EventType.DATA_UPDATE,
        source="data_pipeline",
        subject=dataset,
        payload={"rows": rows, **kwargs},
    )


def make_model_cycle(
    model_name: str,
    mase: float = 0.0,
    smape: float = 0.0,
    horizon: int = 14,
    **kwargs: Any,
) -> Event:
    return Event(
        detail_type=EventType.MODEL_CYCLE,
        source=f"agent.{model_name}",
        payload={"model": model_name, "metrics": {"MASE": mase, "sMAPE": smape}, "horizon": horizon, **kwargs},
    )


def make_telemetry(agent_codename: str, latency_ms: float = 0.0, success: bool = True, **kwargs: Any) -> Event:
    return Event(
        detail_type=EventType.TELEMETRY_AGENT,
        source=f"agent.{agent_codename}",
        payload={"latency_ms": latency_ms, "success": success, **kwargs},
    )
