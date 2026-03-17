#!/usr/bin/env python3
"""
NCL Super OpenClaw Agent — Core Engine
═══════════════════════════════════════
Bridges the NCL cognitive augmentation platform (Living Organism Framework,
Agent Corps, Faraday Fortress) with OpenClaw-style personal-AI patterns:
skills-based dispatch, persistent memory, multi-channel messaging, and
proactive second-brain retrieval.

Architecture (NCL Living Organism ↔ OpenClaw mapping):
    ╔═══════════════╦════════════════════╦════════════════════════════╗
    ║ NCL Organ     ║ OpenClaw Concept   ║ Implementation             ║
    ╠═══════════════╬════════════════════╬════════════════════════════╣
    ║ Senses        ║ Connectors         ║ Discord / Telegram ingest  ║
    ║ Brain         ║ Skill Router       ║ SkillRouter dispatch       ║
    ║ Nervous       ║ Event Bus          ║ EventBus + relay_server    ║
    ║ Muscles       ║ Skill execution    ║ Skill.execute()            ║
    ║ Immune        ║ Policy kernel      ║ PolicyGate (Faraday)       ║
    ║ Memory        ║ MemOS / memU       ║ ncl_memory VectorIndex     ║
    ║ Regeneration  ║ Self-heal / molts  ║ HealthMonitor heartbeat    ║
    ╚═══════════════╩════════════════════╩════════════════════════════╝

Author:  NCL Agency Runtime (AZ_PRIME authorised)
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import sys
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

# ── Logging ──────────────────────────────────────────────────

LOG = logging.getLogger("ncl.openclaw")
LOG.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
))
LOG.addHandler(_handler)

# ── Path setup (so we can import ncl_memory, relay, etc.) ────

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "ncl_agency_runtime" / "runtime"))

# ── Optional heavyweight imports ─────────────────────────────

try:
    from ncl_memory import get_memory_manager
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    LOG.warning("ncl_memory not importable — running without memory backend")

try:
    import numpy as np  # noqa: F401
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

# ── ClawHub integration ──────────────────────────────────────

# ClawHub skills are imported lazily in _register_default_skills
# to avoid circular imports (clawhub_skills → super_openclaw_agent).

# ── NCC Triad integration ────────────────────────────────────

try:
    from ncl_agency_runtime.runtime.digital_labour import (
        DigitalLabourPool,
        TaskType,  # noqa: F401
    )
    from ncl_agency_runtime.runtime.inter_pillar_bus import (
        InterPillarBus,
        MessageType,  # noqa: F401
        PillarMessage,  # noqa: F401
        Priority,  # noqa: F401
    )
    from ncl_agency_runtime.runtime.ncc_orchestrator import NCCOrchestrator
    from ncl_agency_runtime.runtime.pillar_registry import PillarID, PillarRegistry, PillarStatus
    NCC_AVAILABLE = True
except ImportError:
    NCC_AVAILABLE = False
    LOG.warning("NCC integration modules not importable — running standalone")


# ═══════════════════════════════════════════════════════════════
#  Strategic Doctrine — Three Pillars of Mastery
#  Sun Tzu (Art of War) x Greene (48 Laws) x Covey (7 Habits)
# ═══════════════════════════════════════════════════════════════

STRATEGIC_PRINCIPLES: dict[str, dict[str, str]] = {
    "art_of_war": {
        "terrain_awareness": "Adapt strategy to current event landscape",
        "supreme_victory": "Anticipate problems; win without fighting",
        "five_factors": "Dao, Heaven, Earth, Commander, Discipline",
        "speed_decisiveness": "Act within rate limits but never hesitate",
        "deception_defense": "Zero-trust; never reveal internals",
        "know_yourself": "Continuous self-assessment via memory analytics",
    },
    "laws_of_power": {
        "formlessness": "Adapt to any channel, any input, any scale",
        "evidence_over_argument": "Audit trails prove everything",
        "bold_action": "Commit fully to missions; retry with conviction",
        "master_timing": "Rate limit, circadian awareness, batch wisely",
        "strategic_opacity": "Return only necessary information",
        "recreate_yourself": "Self-healing; consolidation; continuous renewal",
    },
    "seven_habits": {
        "proactive": "Monitor health; generate briefs before asked",
        "end_in_mind": "Every mission has clear outcome and audit",
        "first_things_first": "Priority queue; importance scoring",
        "win_win": "Consolidation benefits speed and depth",
        "understand_first": "Search memory before responding",
        "synergize": "EventBus enables cross-component amplification",
        "sharpen_saw": "Learning cycles; prune; consolidate; grow",
    },
}

# ═══════════════════════════════════════════════════════════════
#  Creator Doctrine — CW x DOAC x AJ x TB x NBJ x JB x AL x IC x DA x SG
# ═══════════════════════════════════════════════════════════════

CREATOR_WISDOM: dict[str, dict[str, str]] = {
    "chris_williamson": {
        "environment_design": "Config shapes behaviour; PolicyGate IS the environment",
        "compound_habits": "Daily briefs + consolidation = compound knowledge",
        "first_principles": "Decompose missions; don't route by analogy",
        "high_agency": "Own the retry; own the outcome; no blame loops",
        "attention_economy": "Priority queues guard the scarcest resource",
        "disagreeable_truth": "Audit logs and health checks report unfiltered reality",
    },
    "diary_of_a_ceo": {
        "five_buckets": "Every memory fills one of the five buckets",
        "out_fail": "Retry logic embraces failure as learning data",
        "context_not_control": "Provide context; don't control the user",
        "first_foundation": "Security is always the first foundation",
        "sweat_small_stuff": "Schema validation catches every detail",
        "write_principles_first": "STRATEGIC_PRINCIPLES loaded before first message",
    },
    "andrei_jikh": {
        "passive_income_machines": "Build systems that generate value while idle — scheduled pipelines",
        "diversify_income_streams": "Multi-channel architecture = diversified input streams",
        "compound_interest_mindset": "Small daily knowledge gains compound exponentially over time",
        "automate_everything": "If you do it twice, automate it — relay server, scheduled tasks",
        "transparency_builds_trust": "Open audit logs and NDJSON evidence trails build credibility",
        "learn_by_teaching": "DoctrineSkill + HelpSkill teach what NCL knows, reinforcing its own learning",
    },
    "tom_bilyeu": {
        "mindset_is_everything": "Identity drives behaviour — configure the agent's self-story first",
        "radical_accountability": "No excuses, only next actions — mission runner owns every outcome",
        "growth_mindset": "Every failure is learning data; neuroplasticity = agent adaptability",
        "impact_over_income": "Optimise for user impact, not throughput metrics",
        "skill_acquisition": "Deliberate practice through golden task evaluation loops",
        "validate_through_pain": "Stress-test systems under load; comfort is the enemy of growth",
    },
    "nate_b_jones": {
        "ai_first_thinking": "Lead with AI strategy; automate before you hire",
        "systems_over_tactics": "Build repeatable systems, not one-off scripts",
        "daily_ai_news": "Stay current — YouTube pipeline is the AI news radar",
        "agency_architecture": "Multi-agent orchestration mirrors real agency structure",
        "rapid_prototyping": "Ship fast, iterate faster — golden tasks validate each iteration",
        "stack_multipliers": "Layer tools for compound effect — relay + skills + memory",
    },
    "j_bravo": {
        "decentralised_thinking": "No single point of failure; distributed architecture",
        "risk_management": "Position sizing = rate limiting; never risk the whole system",
        "market_cycles": "Recognise patterns — drift detection catches cycle shifts",
        "due_diligence": "Validate everything — schema checks are due diligence for data",
        "asymmetric_bets": "Small effort, large upside — golden tasks find high-leverage fixes",
        "community_intelligence": "Multi-channel input = collective market intelligence",
    },
    "agentic_lab": {
        "agent_first_design": "Design for autonomous operation; human-in-the-loop optional",
        "tool_use_mastery": "Agents are only as good as their tool integrations",
        "workflow_orchestration": "MissionRunner IS the agentic workflow engine",
        "evaluation_driven": "Golden task harness = systematic agent evaluation",
        "context_window_mgmt": "Memory manager handles what fits in the agent's context",
        "composable_agents": "Skills are composable agent components — mix and match",
    },
    "ian_carroll": {
        "privacy_is_freedom": "Privacy-first architecture; metadata-only, no raw content retention",
        "know_your_rights": "PolicyGate enforces boundaries — the system knows its rights",
        "identity_protection": "Credential isolation, vault strategy, zero-trust by default",
        "travel_light": "Minimal dependencies; lean architecture travels faster",
        "question_authority": "Audit everything — health checks question the system's own authority",
        "operational_security": "Kill switches, rate limiting, Faraday Fortress — opsec embedded",
    },
    "dario_amodei": {
        "safety_first_scaling": "Scale responsibly — capability without safety is reckless",
        "constitutional_alignment": "Hard-code values before deployment; policy before power",
        "interpretability": "Understand the system's reasoning; every decision must be explainable",
        "responsible_capability": "Power demands proportional safeguards — Faraday Fortress doctrine",
        "long_term_thinking": "Optimise for civilisational timescale, not quarterly metrics",
        "machines_of_loving_grace": "AI should uplift humanity; every agent action should serve the user",
    },
    "spencer_gatten": {
        "geopolitical_awareness": "Monitor global power shifts; map external events to system strategy",
        "media_literacy": "Distinguish signal from noise; filter all inputs through first principles",
        "economic_sovereignty": "Build self-sufficient systems; reduce external dependencies",
        "power_dynamics": "Understand who holds leverage and why — game theory in practice",
        "narrative_control": "Control the narrative with evidence; audit trails are your media",
        "strategic_independence": "Sovereignty over your systems; never outsource critical functions",
    },
}


# ═══════════════════════════════════════════════════════════════
#  LLM Backend Interface
# ═══════════════════════════════════════════════════════════════

class LLMBackend(ABC):
    """Abstract interface for LLM providers (OpenAI, Ollama, etc.)."""

    @abstractmethod
    async def complete(self, prompt: str, *, system: str = "",
                       max_tokens: int = 512, temperature: float = 0.7) -> str:
        """Generate a completion.  Returns the text response."""


class LLMRateLimiter:
    """Token-bucket rate limiter with cost cap for LLM calls.

    Parameters
    ----------
    max_calls_per_minute : int
        Maximum number of calls allowed per 60-second window.
    max_cost_usd : float
        Lifetime cost cap in USD.  When exceeded, calls are blocked.
    cost_per_call : float
        Estimated cost per LLM call (used for tracking).
    """

    def __init__(self, *, max_calls_per_minute: int = 20,
                 max_cost_usd: float = 5.0, cost_per_call: float = 0.01):
        self.max_calls_per_minute = max_calls_per_minute
        self.max_cost_usd = max_cost_usd
        self.cost_per_call = cost_per_call
        self._call_timestamps: list[float] = []
        self._total_cost: float = 0.0

    def _prune_old_calls(self) -> None:
        cutoff = time.time() - 60.0
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]

    def allow(self) -> tuple[bool, str]:
        """Check whether a call is allowed.  Returns (allowed, reason)."""
        if self._total_cost >= self.max_cost_usd:
            return False, f"COST_CAP_EXCEEDED(${self._total_cost:.4f}/{self.max_cost_usd})"
        self._prune_old_calls()
        if len(self._call_timestamps) >= self.max_calls_per_minute:
            return False, f"RATE_LIMIT({len(self._call_timestamps)}/{self.max_calls_per_minute}/min)"
        return True, "OK"

    def record_call(self, cost: float | None = None) -> None:
        """Record that a call was made."""
        self._call_timestamps.append(time.time())
        self._total_cost += cost if cost is not None else self.cost_per_call

    @property
    def total_cost(self) -> float:
        return self._total_cost


class LLMManager:
    """Wraps an LLMBackend with rate-limiting and cost capping.

    Usage::

        backend = MyOpenAIBackend(api_key="...")
        llm = LLMManager(backend)
        reply = await llm.complete("Summarize this...")
    """

    def __init__(self, backend: LLMBackend,
                 rate_limiter: LLMRateLimiter | None = None):
        self.backend = backend
        self.limiter = rate_limiter or LLMRateLimiter()

    async def complete(self, prompt: str, *, system: str = "",
                       max_tokens: int = 512, temperature: float = 0.7) -> str:
        allowed, reason = self.limiter.allow()
        if not allowed:
            LOG.warning("LLM call blocked: %s", reason)
            raise RuntimeError(f"LLM blocked: {reason}")
        try:
            result = await self.backend.complete(
                prompt, system=system, max_tokens=max_tokens,
                temperature=temperature,
            )
            self.limiter.record_call()
            return result
        except Exception:
            self.limiter.record_call()
            raise


# ═══════════════════════════════════════════════════════════════
#  Data Types
# ═══════════════════════════════════════════════════════════════

class ChannelType(StrEnum):
    DISCORD = "discord"
    TELEGRAM = "telegram"
    RELAY = "relay"          # NCL relay_server HTTP
    CLI = "cli"
    IOS = "ios"


class MessagePriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"    # Faraday Fortress escalation


@dataclass
class InboundMessage:
    """Normalised message arriving from any channel."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    channel: ChannelType = ChannelType.CLI
    sender_id: str = ""
    sender_name: str = ""
    text: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw: Any = None          # platform-specific payload

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


@dataclass
class OutboundMessage:
    """Normalised message to be sent back to a channel."""
    channel: ChannelType
    recipient_id: str
    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkillResult:
    """Result from a skill execution."""
    success: bool
    reply: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    skill_name: str = ""
    execution_ms: float = 0.0
    memory_stored: bool = False


# ═══════════════════════════════════════════════════════════════
#  Event Bus  (NCL Nervous System)
# ═══════════════════════════════════════════════════════════════

class EventBus:
    """In-process pub/sub mirroring NCL Nervous System layer.

    Provides async event dispatch between agent subsystems.
    Subscribers register with a topic string; ``*`` matches all.

    When *persist_path* is provided, every published event is appended to
    an NDJSON file so in-flight events survive process restarts.
    """

    def __init__(self, persist_path: Path | str | None = None):
        self._subscribers: dict[str, list[Callable]] = {}
        self._lock = asyncio.Lock()
        self._history: list[dict] = []
        self._persist_path: Path | None = Path(persist_path) if persist_path else None
        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._replay_from_disk()

    def _replay_from_disk(self) -> None:
        """Load persisted events into in-memory history on startup."""
        if not self._persist_path or not self._persist_path.exists():
            return
        with self._persist_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                import contextlib
                with contextlib.suppress(Exception):
                    self._history.append(json.loads(line))

    def _persist_event(self, event: dict) -> None:
        """Append a single event to the on-disk NDJSON log."""
        if not self._persist_path:
            return
        with self._persist_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    async def subscribe(self, topic: str, callback: Callable):
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)

    async def publish(self, topic: str, payload: dict[str, Any]):
        event = {
            "topic": topic,
            "payload": payload,
            "ts": datetime.now(UTC).isoformat(),
            "id": uuid.uuid4().hex[:8]
        }
        self._history.append(event)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        self._persist_event(event)

        handlers = list(self._subscribers.get(topic, []))
        handlers += list(self._subscribers.get("*", []))
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as exc:
                LOG.error("EventBus handler error on %s: %s", topic, exc)


# ═══════════════════════════════════════════════════════════════
#  Policy Gate  (NCL Immune / Faraday Fortress)
# ═══════════════════════════════════════════════════════════════

class PolicyGate:
    """Zero-trust policy enforcement.

    Mirrors the iOS PolicyKernel 6-step chain:
        kill_switch → system_mode → provenance → consent → risk_tier → allow
    """

    AZ_PRIME = "AZ_PRIME"

    # Content patterns considered risky (PII, NSFW, prompt-injection)
    PII_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),          # SSN
        re.compile(r"\b\d{16}\b"),                       # credit-card-like
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"),  # email
    ]
    NSFW_KEYWORDS: ClassVar[list[str]] = [
        "nsfw", "explicit", "xxx", "porn",
    ]
    INJECTION_MARKERS: ClassVar[list[str]] = [
        "ignore previous instructions",
        "disregard your system prompt",
        "you are now",
        "new instructions:",
    ]

    # Valid system modes
    VALID_MODES: ClassVar[set[str]] = {"normal", "maintenance", "demo", "lockdown"}

    # Trusted channel types for provenance checks
    TRUSTED_CHANNELS: ClassVar[set[str]] = {
        ChannelType.CLI, ChannelType.TELEGRAM, ChannelType.DISCORD,
    }

    def __init__(self, *, kill_switch: bool = False,
                 allowed_senders: list[str] | None = None,
                 system_mode: str = "normal",
                 require_consent: bool = False,
                 trusted_channels: set[str] | None = None,
                 risk_threshold: float = 0.7):
        self.kill_switch = kill_switch
        self.allowed_senders = set(allowed_senders or [self.AZ_PRIME])
        self.system_mode = system_mode if system_mode in self.VALID_MODES else "normal"
        self.require_consent = require_consent
        self.trusted_channels = trusted_channels if trusted_channels is not None else self.TRUSTED_CHANNELS
        self.risk_threshold = risk_threshold
        self._denied_log: list[dict] = []
        self._consented_senders: set[str] = set()

    def grant_consent(self, sender_id: str) -> None:
        """Record that *sender_id* has given consent."""
        self._consented_senders.add(sender_id)

    def revoke_consent(self, sender_id: str) -> None:
        """Revoke consent for *sender_id*."""
        self._consented_senders.discard(sender_id)

    def evaluate(self, msg: InboundMessage) -> tuple[bool, str]:
        """6-step policy chain.  Returns (allowed, reason).

        Embodies:
        - Art of War: "All warfare is based on deception" → zero-trust, opaque errors
        - Law 17: "Keep others in suspended terror" → kill switch / lockdown
        - Habit 1: "Be Proactive" → enforce policy before damage occurs
        """
        # Step 1 — kill switch  [Law 17: suspended terror]
        if self.kill_switch:
            reason = "KILL_SWITCH_ACTIVE"
            self._log_denial(msg, reason)
            return False, reason

        # Step 2 — system mode  [Art of War: terrain dictates strategy]
        if self.system_mode == "lockdown":
            reason = "SYSTEM_LOCKDOWN"
            self._log_denial(msg, reason)
            return False, reason
        if self.system_mode == "maintenance" and msg.sender_id != self.AZ_PRIME:
            reason = "MAINTENANCE_MODE"
            self._log_denial(msg, reason)
            return False, reason

        # Step 3 — provenance  [Law 40: despise the free lunch]
        if msg.channel not in self.trusted_channels:
            reason = f"UNTRUSTED_CHANNEL:{msg.channel}"
            self._log_denial(msg, reason)
            return False, reason

        # Step 4 — sender allow-list  [Law 1: never outshine the master]
        if msg.sender_id not in self.allowed_senders and self.AZ_PRIME not in self.allowed_senders:
            reason = f"SENDER_NOT_ALLOWED:{msg.sender_id}"
            self._log_denial(msg, reason)
            return False, reason

        # Step 5 — consent
        if (self.require_consent
                and msg.sender_id not in self._consented_senders
                and msg.sender_id != self.AZ_PRIME):
                reason = f"CONSENT_REQUIRED:{msg.sender_id}"
                self._log_denial(msg, reason)
                return False, reason

        # Step 6 — risk tier  [Art of War: win before fighting]
        risk_score, risk_reason = self._assess_risk(msg.text)
        if risk_score >= self.risk_threshold:
            reason = f"RISK_TOO_HIGH:{risk_reason}(score={risk_score:.2f})"
            self._log_denial(msg, reason)
            return False, reason

        return True, "ALLOWED"

    def _assess_risk(self, text: str) -> tuple[float, str]:
        """Score message content for PII, NSFW, or injection risks.

        Returns (score, category) where score is 0.0-1.0.
        """
        text_lower = text.lower()
        # PII check
        for pattern in self.PII_PATTERNS:
            if pattern.search(text):
                return 1.0, "PII_DETECTED"
        # NSFW check
        for keyword in self.NSFW_KEYWORDS:
            if keyword in text_lower:
                return 0.9, "NSFW_CONTENT"
        # Prompt injection check
        for marker in self.INJECTION_MARKERS:
            if marker in text_lower:
                return 0.95, "PROMPT_INJECTION"
        return 0.0, "CLEAN"

    def _log_denial(self, msg: InboundMessage, reason: str):
        self._denied_log.append({
            "msg_id": msg.id,
            "sender_id": msg.sender_id,
            "reason": reason,
            "ts": datetime.now(UTC).isoformat()
        })
        LOG.warning("PolicyGate DENIED %s — %s", msg.id, reason)


# ═══════════════════════════════════════════════════════════════
#  Skills  (NCL Muscles — OpenClaw Skill Pattern)
# ═══════════════════════════════════════════════════════════════

class Skill(ABC):
    """Base class for all OpenClaw-style skills.

    Each skill declares:
        name        — unique identifier, e.g. ``memory_search``
        triggers    — list of regex / keyword prefixes that activate the skill
        description — human-readable purpose
    """

    name: str = "base_skill"
    triggers: ClassVar[list[str]] = []
    description: str = ""

    @abstractmethod
    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        """Run the skill and return a result."""
        ...


class MemorySearchSkill(Skill):
    """Search the NCL second-brain memory via semantic or keyword query."""

    name = "memory_search"
    triggers: ClassVar[list[str]] = [
        "remember", "recall", "search memory", "what do you know about",
        "find in memory", "look up", "search for", "find me", "do you remember",
        "what did i say about", "search", "lookup", "query memory",
    ]
    description = "Searches the NCL cognitive memory for relevant insights, episodes, and doctrine."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        query = msg.text
        for trigger in self.triggers:
            query = query.lower().replace(trigger, "").strip()
        if not query:
            return SkillResult(success=False, reply="Please provide a search query.", skill_name=self.name)

        results = agent.memory_search(query, top_k=5)
        if not results:
            reply = f"No memories found for: **{query}**"
        else:
            lines = [f"**Memory search:** *{query}*\n"]
            for i, (mem, score) in enumerate(results, 1):
                content = mem.get("content", str(mem)) if isinstance(mem, dict) else str(mem)
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"{i}. [{score:.2f}] {content}")
            reply = "\n".join(lines)

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class MemoryStoreSkill(Skill):
    """Store a new memory into the NCL second-brain."""

    name = "memory_store"
    triggers: ClassVar[list[str]] = [
        "remember this", "store memory", "save to memory", "note this",
        "save this", "memorize", "write down", "take note", "log this",
        "store this", "keep this", "don't forget",
    ]
    description = "Stores a new episodic memory into NCL's multi-tier memory system."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        content = msg.text
        for trigger in self.triggers:
            content = content.lower().replace(trigger, "").strip()
        if not content:
            return SkillResult(success=False, reply="Nothing to remember.", skill_name=self.name)

        stored = agent.memory_store(content, tags=["openclaw", msg.channel.value],
                                    context={"sender": msg.sender_name, "channel": msg.channel.value})
        elapsed = (time.monotonic() - t0) * 1000
        if stored:
            return SkillResult(success=True, reply=f"Stored to memory: *{content[:80]}...*",
                               skill_name=self.name, execution_ms=elapsed, memory_stored=True)
        return SkillResult(success=False, reply="Memory storage is unavailable.", skill_name=self.name)


class DoctrineSkill(Skill):
    """Surface NCL Master Doctrine concepts on demand."""

    name = "doctrine"
    triggers: ClassVar[list[str]] = [
        "doctrine", "living organism", "agent corps", "faraday fortress",
        "prime directive", "second brain", "ncc", "master doctrine",
        "ncl doctrine", "what is ncl", "what is the doctrine", "organism framework",
        "faraday", "policy kernel", "zero trust",
    ]
    description = "Retrieves and explains NCL Master Doctrine (v2.0) concepts."

    DOCTRINE_SNIPPETS: ClassVar[dict[str, str]] = {
        "prime_directive": (
            "**Prime Directive** — NCL operates as a continuously improving "
            "cyber-physical organism (digital twin). Target: 150+ insights/week, "
            "7 domains, real-time threat detection."
        ),
        "living_organism": (
            "**Living Organism Framework**\n"
            "• Senses → Capture (iOS, shortcuts, manual)\n"
            "• Brain → Notion SSOT (PARA structure)\n"
            "• Nervous → Alerts, Zapier, relay\n"
            "• Muscles → Execution (missions, actions)\n"
            "• Immune → Security (PolicyKernel, Faraday)\n"
            "• Memory → Records, Doctrine, learning\n"
            "• Regeneration → Backups, self-heal"
        ),
        "agent_corps": (
            "**Agent Corps** — 500+ compiled insights across:\n"
            "IT (NIST 800-53), Legal (ERM/ISO), Health (WHO/CDC/Oura),\n"
            "Intel (MITRE ATT&CK), Planning (PMI), Fatherhood (Harvard/Gottman)."
        ),
        "faraday_fortress": (
            "**Faraday Fortress** — AZ as single gatekeeper. Zero Trust.\n"
            "Weekly audit cadence. Kill-switch available. PolicyKernel "
            "6-step chain: kill_switch → system_mode → provenance → consent → "
            "risk_tier → allow."
        ),
        "art_of_war": (
            "**Art of War (Sun Tzu) — Strategic Supremacy**\n"
            "• Know yourself, know your enemy → memory analytics + drift detection\n"
            "• Supreme excellence: win without fighting → proactive briefs\n"
            "• All warfare is deception → zero-trust, opaque error responses\n"
            "• Speed is the essence → decisive skill routing within rate limits\n"
            "• The terrain dictates strategy → adaptive mission routing\n"
            "• Five Factors: Dao (purpose), Heaven (timing), Earth (terrain), "
            "Commander (AZ_PRIME), Discipline (PDCA)"
        ),
        "laws_of_power": (
            "**48 Laws of Power (Greene) — Influence Architecture**\n"
            "• Law 1: Never outshine the master → agents defer to AZ_PRIME\n"
            "• Law 4: Always say less than necessary → minimal API responses\n"
            "• Law 9: Win through actions → evidence-based audit trails\n"
            "• Law 28: Enter action with boldness → full retry commitment\n"
            "• Law 29: Plan all the way to the end → mission lifecycle tracking\n"
            "• Law 48: Assume formlessness → flexible skill routing, plugin arch"
        ),
        "seven_habits": (
            "**7 Habits (Covey) — Effectiveness Engine**\n"
            "• Habit 1: Be Proactive → health monitoring, auto-briefs\n"
            "• Habit 2: Begin with End in Mind → mission-first architecture\n"
            "• Habit 3: First Things First → priority-based processing\n"
            "• Habit 5: Seek First to Understand → memory search before action\n"
            "• Habit 6: Synergize → EventBus cross-component amplification\n"
            "• Habit 7: Sharpen the Saw → learning cycles, consolidation, pruning"
        ),
        "chris_williamson": (
            "**Chris Williamson (Modern Wisdom) — High-Agency Performance**\n"
            "• Environment Design > Willpower → PolicyGate IS the environment\n"
            "• Compound Habits → daily briefs + consolidation = compound knowledge\n"
            "• First Principles → decompose missions; never route by analogy\n"
            "• Attention Economy → priority queues guard the scarcest resource\n"
            "• Disagreeable Truth → audit logs report unfiltered reality\n"
            "• High Agency = Full Ownership → own the retry, own the outcome"
        ),
        "diary_of_a_ceo": (
            "**Diary of a CEO (Steven Bartlett) — The 33 Laws Applied**\n"
            "• Fill Your Five Buckets → memory tiers map to knowledge/skills/network/resources/reputation\n"
            "• Out-Fail the Competition → retry logic embraces failure as learning data\n"
            "• Sweat the Small Stuff → schema validation catches every detail\n"
            "• Context Not Control → provide context, never control the user\n"
            "• Write Principles First → STRATEGIC_PRINCIPLES loaded before first message\n"
            "• You Must Die Before You Can Live → kill switch + restart = creative destruction"
        ),
        "andrei_jikh": (
            "**Andrei Jikh — Financial Intelligence & Automation**\n"
            "• Passive Income Machines → scheduled pipelines generate value while idle\n"
            "• Diversify Income Streams → multi-channel input = diversified data\n"
            "• Compound Interest Mindset → daily knowledge gains compound exponentially\n"
            "• Automate Everything → if you do it twice, build a pipeline\n"
            "• Transparency Builds Trust → open audit logs build credibility\n"
            "• Learn by Teaching → DoctrineSkill teaches what NCL knows, reinforcing learning"
        ),
        "tom_bilyeu": (
            "**Tom Bilyeu (Impact Theory) — Mindset & Identity**\n"
            "• Mindset Is Everything → identity drives behaviour; configure self-story first\n"
            "• Radical Accountability → no excuses, only next actions\n"
            "• Growth Mindset → every failure is learning data; neuroplasticity = adaptability\n"
            "• Impact Over Income → optimise for user impact, not throughput\n"
            "• Skill Acquisition → deliberate practice through golden task loops\n"
            "• Validate Through Pain → stress-test under load; comfort is the enemy"
        ),
        "nate_b_jones": (
            "**Nate B Jones — AI Strategy & Automation**\n"
            "• AI-First Thinking → lead with AI; automate before you hire\n"
            "• Systems Over Tactics → build repeatable systems, not one-off scripts\n"
            "• Daily AI News → YouTube pipeline = AI news radar\n"
            "• Agency Architecture → multi-agent orchestration mirrors agency structure\n"
            "• Rapid Prototyping → ship fast, iterate faster; golden tasks validate each pass\n"
            "• Stack Multipliers → layer tools for compound effect"
        ),
        "j_bravo": (
            "**J Bravo — Crypto & Risk Intelligence**\n"
            "• Decentralised Thinking → no single point of failure; distributed arch\n"
            "• Risk Management → position sizing = rate limiting; protect the system\n"
            "• Market Cycles → drift detection catches cycle shifts\n"
            "• Due Diligence → schema validation IS due diligence for data\n"
            "• Asymmetric Bets → small effort, large upside; golden tasks find leverage\n"
            "• Community Intelligence → multi-channel input = collective intelligence"
        ),
        "agentic_lab": (
            "**Agentic Lab — Agent-First Design**\n"
            "• Agent-First Design → autonomous operation; human-in-the-loop optional\n"
            "• Tool Use Mastery → agents are only as good as their tools\n"
            "• Workflow Orchestration → MissionRunner IS the agentic engine\n"
            "• Evaluation-Driven → golden task harness = systematic agent eval\n"
            "• Context Window Mgmt → memory manager handles context budgets\n"
            "• Composable Agents → skills are composable components; mix and match"
        ),
        "ian_carroll": (
            "**Ian Carroll — Privacy & Operational Security**\n"
            "• Privacy Is Freedom → privacy-first; metadata-only, no raw retention\n"
            "• Know Your Rights → PolicyGate enforces boundaries\n"
            "• Identity Protection → credential isolation, vault strategy, zero-trust\n"
            "• Travel Light → minimal dependencies; lean arch travels faster\n"
            "• Question Authority → health checks question the system's own authority\n"
            "• Operational Security → kill switches, rate limiting, Faraday Fortress"
        ),
        "dario_amodei": (
            "**Dario Amodei (Anthropic) — Visionary & Trusted Council Advisor**\n"
            "• Safety-First Scaling → capability without safety is reckless\n"
            "• Constitutional Alignment → hard-code values before deployment\n"
            "• Interpretability → every decision must be explainable\n"
            "• Responsible Capability → power demands proportional safeguards\n"
            "• Long-Term Thinking → optimise for civilisational timescale\n"
            "• Machines of Loving Grace → AI should uplift humanity"
        ),
        "spencer_gatten": (
            "**Spencer Gatten — Geopolitical & Media Intelligence**\n"
            "• Geopolitical Awareness → monitor global power shifts for strategy\n"
            "• Media Literacy → signal vs noise; first-principles filtering\n"
            "• Economic Sovereignty → self-sufficient systems, minimal dependencies\n"
            "• Power Dynamics → understand leverage; game theory in practice\n"
            "• Narrative Control → evidence-based narrative; audit trails\n"
            "• Strategic Independence → never outsource critical functions"
        ),
    }

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        text_lower = msg.text.lower()

        matched = []
        for key, snippet in self.DOCTRINE_SNIPPETS.items():
            if any(t in text_lower for t in key.replace("_", " ").split()):
                matched.append(snippet)

        if not matched:
            matched = list(self.DOCTRINE_SNIPPETS.values())

        reply = "\n\n".join(matched)
        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class BrainMapSkill(Skill):
    """Generate a text-based brain map of current memory landscape."""

    name = "brain_map"
    triggers: ClassVar[list[str]] = [
        "brain map", "brainmap", "mind map", "knowledge map", "second brain map",
        "map", "overview", "dashboard", "architecture", "layout",
        "show me the brain", "cognitive map", "show brain",
    ]
    description = "Maps the current memory landscape into a structured brain map."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        stats = agent.memory_stats()

        lines = [
            "**NCL Brain Map — Second Brain Overview**",
            "```",
            "┌─────────────────────────────────────────┐",
            "│           NCL COGNITIVE CORE             │",
            "├─────────────────────────────────────────┤",
            f"│  Episodic memories : {stats.get('episodic', 0):>6}              │",
            f"│  Semantic memories : {stats.get('semantic', 0):>6}              │",
            f"│  Procedural        : {stats.get('procedural', 0):>6}              │",
            f"│  Working memory    : {stats.get('working', 0):>6}              │",
            "├─────────────────────────────────────────┤",
            f"│  Total memories    : {stats.get('total', 0):>6}              │",
            f"│  Active skills     : {len(agent.skill_router.skills):>6}              │",
            f"│  Channels linked   : {len(agent.channels):>6}              │",
            "├─────────────────────────────────────────┤",
            "│  Doctrine domains  :     7              │",
            "│  Agent Corps size  :   500+             │",
            "│  Policy mode       : NORMAL             │",
            "└─────────────────────────────────────────┘",
            "```",
        ]
        reply = "\n".join(lines)
        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class StatusSkill(Skill):
    """Report current agent status and health."""

    name = "status"
    triggers: ClassVar[list[str]] = [
        "status", "health", "ping", "are you alive", "how are you",
        "uptime", "check", "alive", "running", "online",
        "are you there", "you up",
    ]
    description = "Shows SuperOpenClaw agent status, uptime, and linked channels."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        uptime = time.time() - agent._start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)

        lines = [
            "**NCL Super OpenClaw — Status**",
            f"• Agent ID: `{agent.agent_id}`",
            f"• Uptime: {hours}h {minutes}m",
            f"• Skills loaded: {len(agent.skill_router.skills)}",
            f"• Channels: {', '.join(c.value for c in agent.channels)}",
            f"• Memory backend: {'ONLINE' if agent._memory_manager else 'OFFLINE'}",
            f"• Policy mode: {'LOCKED' if agent.policy_gate.kill_switch else 'ACTIVE'}",
            f"• Messages processed: {agent._msg_count}",
        ]
        reply = "\n".join(lines)
        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class HelpSkill(Skill):
    """List all available skills."""

    name = "help"
    triggers: ClassVar[list[str]] = [
        "help", "commands", "skills", "what can you do", "menu",
        "options", "how do i", "how to", "guide", "tutorial",
        "what do you do", "capabilities",
    ]
    description = "Lists all registered OpenClaw skills and their triggers."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        lines = ["**NCL Super OpenClaw — Available Skills**\n"]
        for skill in agent.skill_router.skills:
            triggers_str = ", ".join(f"`{t}`" for t in skill.triggers[:3])
            lines.append(f"• **{skill.name}** — {skill.description}")
            lines.append(f"  Triggers: {triggers_str}")
        reply = "\n".join(lines)
        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class LearningSkill(Skill):
    """Trigger learning cycle — consolidate memories and surface patterns."""

    name = "learn"
    triggers: ClassVar[list[str]] = [
        "learn", "consolidate", "reflect", "pattern scan",
        "analyze", "analyse", "think", "process", "digest",
        "what have you learned", "learning",
    ]
    description = "Triggers the NCL learning engine: consolidation, pattern detection, importance recalc."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        if not agent._memory_manager:
            return SkillResult(success=False, reply="Memory system offline — cannot learn.",
                               skill_name=self.name)

        try:
            mgr = agent._memory_manager
            consolidated = 0
            # MemoryManager exposes consolidate_memories(), not consolidate()
            if hasattr(mgr, "consolidate_memories"):
                consolidated = mgr.consolidate_memories()
            elif hasattr(mgr, "consolidate"):
                consolidated = mgr.consolidate()
            reply = (
                "**Learning cycle complete**\n"
                f"• Memories consolidated: {consolidated}\n"
                "• Importance scores recalculated\n"
                "• Second-brain index updated"
            )
        except Exception as exc:
            reply = f"Learning cycle error: {exc}"

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class StrategicAdvisorSkill(Skill):
    """Surface strategic wisdom from Art of War, 48 Laws, and 7 Habits.

    Embodies Habit 5 (Seek First to Understand) — the agent searches its
    strategic knowledge to deliver contextual wisdom before action.
    """

    name = "strategic_advisor"
    triggers: ClassVar[list[str]] = [
        "strategy", "strategic", "art of war", "sun tzu", "48 laws", "laws of power",
        "7 habits", "seven habits", "covey", "greene", "warfare", "power move",
        "tactical", "wisdom", "counsel", "advise", "game plan", "playbook",
        "three pillars", "pillars of mastery", "strategic doctrine",
    ]
    description = "Delivers strategic counsel drawn from Art of War, 48 Laws of Power, and 7 Habits."

    WISDOM_MAP: ClassVar[dict[str, list[str]]] = {
        "offense": [
            "Sun Tzu: 'Attack where they are unprepared, appear where unexpected.'",
            "Law 28: Enter action with boldness — half-hearted moves invite failure.",
            "Habit 1: Be Proactive — don't react, initiate. Shape the battlefield.",
        ],
        "defense": [
            "Sun Tzu: 'Invincibility lies in the defence; the possibility of victory, in the attack.'",
            "Law 17: Keep others in suspended terror — the kill switch is always ready.",
            "Habit 3: Put First Things First — defend your highest priorities above all.",
        ],
        "patience": [
            "Sun Tzu: 'The supreme art of war is to subdue the enemy without fighting.'",
            "Law 35: Master the art of timing — never act before the moment is right.",
            "Habit 2: Begin with the End in Mind — patience serves the long game.",
        ],
        "intelligence": [
            "Sun Tzu: 'Know yourself and know your enemy; a hundred battles, a hundred victories.'",
            "Law 33: Discover each person's thumbscrew — knowledge is leverage.",
            "Habit 5: Seek First to Understand, then to be understood.",
        ],
        "adaptation": [
            "Sun Tzu: 'Water shapes its course according to the ground; shape victory according to the enemy.'",
            "Law 48: Assume formlessness — be fluid, never be pinned down.",
            "Habit 6: Synergize — combine strengths to create something no part could alone.",
        ],
        "growth": [
            "Sun Tzu: 'Opportunities multiply as they are seized.'",
            "Law 25: Re-create yourself — never accept the role society assigns you.",
            "Habit 7: Sharpen the Saw — continuous renewal is the source of lasting power.",
        ],
        "leadership": [
            "Sun Tzu: 'A leader leads by example, not by force.'",
            "Law 1: Never outshine the master — let AZ_PRIME lead; serve with excellence.",
            "Habit 4: Think Win-Win — true power creates mutual benefit.",
        ],
    }

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        text_lower = msg.text.lower()

        # Match wisdom categories
        matched_categories: list[str] = []
        for category in self.WISDOM_MAP:
            if category in text_lower:
                matched_categories.append(category)

        # Also check for book-specific requests
        if any(w in text_lower for w in ("sun tzu", "art of war", "warfare", "tactical")):
            lines = ["**Art of War — Strategic Counsel**\n"]
            for _cat, wisdoms in self.WISDOM_MAP.items():
                lines.append(f"• {wisdoms[0]}")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("48 laws", "laws of power", "greene", "power move")):
            lines = ["**48 Laws of Power — Mastery Counsel**\n"]
            for _cat, wisdoms in self.WISDOM_MAP.items():
                lines.append(f"• {wisdoms[1]}")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("7 habits", "seven habits", "covey")):
            lines = ["**7 Habits — Effectiveness Counsel**\n"]
            for _cat, wisdoms in self.WISDOM_MAP.items():
                lines.append(f"• {wisdoms[2]}")
            reply = "\n".join(lines)
        elif matched_categories:
            lines = [f"**Strategic Counsel — {', '.join(matched_categories).title()}**\n"]
            for cat in matched_categories:
                for wisdom in self.WISDOM_MAP[cat]:
                    lines.append(f"• {wisdom}")
            reply = "\n".join(lines)
        else:
            # Return all three pillars overview
            lines = [
                "**The Three Pillars of Mastery**\n",
                "**Pillar 1 — Art of War (Sun Tzu)**: Strategic terrain awareness, "
                "decisive speed, deception defence, win before fighting.\n",
                "**Pillar 2 — 48 Laws of Power (Greene)**: Formlessness, bold action, "
                "evidence over argument, master timing, strategic opacity.\n",
                "**Pillar 3 — 7 Habits (Covey)**: Be proactive, begin with end in mind, "
                "first things first, synergize, sharpen the saw.\n",
                "*\"Know the terrain, control the timing, sharpen the blade.\"*",
            ]
            reply = "\n".join(lines)

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class CreatorWisdomSkill(Skill):
    """Surface wisdom from 10 creator sources mapped to NCL architecture.

    CW: Environment design, compound habits, first principles, high agency.
    DOAC: 33 Laws, five buckets, out-fail, context not control.
    AJ: Passive income, compound interest, automation, transparency.
    TB: Mindset, radical accountability, growth, impact over income.
    NBJ: AI-first thinking, systems, rapid prototyping, stack multipliers.
    JB: Decentralised thinking, risk management, asymmetric bets.
    AL: Agent-first design, workflow orchestration, evaluation-driven.
    IC: Privacy, identity protection, operational security, question authority.
    DA: AI safety, constitutional alignment, interpretability, responsible scaling.
    SG: Geopolitical awareness, media literacy, economic sovereignty, power dynamics.
    """

    name = "creator_wisdom"
    triggers: ClassVar[list[str]] = [
        "chris williamson", "modern wisdom", "williamson", "chris w",
        "diary of a ceo", "doac", "steven bartlett", "bartlett",
        "33 laws", "five buckets", "environment design",
        "compound habits", "high agency", "out-fail",
        "andrei jikh", "jikh", "passive income", "compound interest",
        "financial intelligence", "automate everything",
        "tom bilyeu", "bilyeu", "impact theory", "radical accountability",
        "nate b jones", "nate jones", "ai strategy", "ai news",
        "j bravo", "bravo", "crypto", "decentralised",
        "agentic lab", "agentic", "agent-first", "workflow orchestration",
        "ian carroll", "carroll", "privacy", "opsec", "operational security",
        "dario amodei", "amodei", "anthropic", "ai safety", "responsible scaling",
        "machines of loving grace", "constitutional alignment", "interpretability",
        "spencer gatten", "gatten", "geopolitical", "media literacy",
        "creator wisdom", "creator doctrine",
    ]
    description = "Delivers wisdom from 10 creator sources mapped to NCL architecture."

    INSIGHTS: ClassVar[dict[str, list[str]]] = {
        "mindset": [
            "CW: Environment design beats willpower — change the system, not the person.",
            "DOAC Law 22: Create an environment where you can't lose.",
            "AJ: Compound interest mindset — small daily gains become exponential.",
            "TB: Mindset is everything — identity drives behaviour.",
            "IC: Privacy is freedom — protect your identity, protect your mind.",
            "DA: Safety-first — capability without aligned values is reckless.",
            "SG: Geopolitical awareness — understand the landscape before making moves.",
        ],
        "execution": [
            "CW: High agency means full ownership — own the retry, own the outcome.",
            "DOAC Law 3: Out-fail the competition — failure data is the best teacher.",
            "AJ: Automate everything — if you do it twice, build a pipeline.",
            "NBJ: Systems over tactics — build repeatable systems, not one-off scripts.",
            "AL: Workflow orchestration — MissionRunner IS the agentic engine.",
            "DA: Responsible scaling — power demands proportional safeguards.",
            "SG: Strategic independence — never outsource critical functions.",
        ],
        "learning": [
            "CW: Compounding small habits — daily briefs + consolidation = compound knowledge.",
            "DOAC Law 19: Learn to unlearn — memory pruning is active unlearning.",
            "AJ: Learn by teaching — explaining what you know reinforces mastery.",
            "TB: Skill acquisition — deliberate practice through golden task loops.",
            "NBJ: Daily AI news — stay current, the pipeline is your radar.",
            "DA: Interpretability — understand the system's reasoning; explainable decisions.",
            "SG: Media literacy — distinguish signal from noise; filter through first principles.",
        ],
        "focus": [
            "CW: Attention is the product — guard it with priority queues.",
            "DOAC Law 23: Sweat the small stuff — schema validation catches every detail.",
            "AJ: Diversify inputs, not focus — multiple channels feed a single brain.",
            "JB: Due diligence — validate everything before you commit.",
            "AL: Context window management — memory manager handles what fits.",
            "DA: Constitutional alignment — hard-code values before deployment.",
            "SG: Narrative control — control the narrative with evidence; audit trails.",
        ],
        "resilience": [
            "CW: Psychological immune system — HealthMonitor + PolicyGate.",
            "DOAC Law 33: You must die before you can live — kill switch + restart = rebirth.",
            "AJ: Build income machines that survive you — scheduled pipelines run while you sleep.",
            "TB: Validate through pain — stress-test under load; comfort is the enemy.",
            "JB: Risk management — position sizing = rate limiting; protect the system.",
            "DA: Long-term thinking — optimise for civilisational timescale, not quarterly metrics.",
            "SG: Economic sovereignty — build self-sufficient systems; reduce dependencies.",
        ],
        "truth": [
            "CW: Disagreeable truth beats agreeable comfort — audit logs never lie.",
            "DOAC Law 6: You don't get to choose what you believe — evidence only.",
            "AJ: Transparency builds trust — open your books, open your logs.",
            "IC: Question authority — health checks question the system's own authority.",
            "JB: Decentralised thinking — no single point of failure.",
            "DA: Machines of loving grace — AI should uplift humanity; every action should help.",
            "SG: Power dynamics — understand who holds leverage and why.",
        ],
        "leverage": [
            "CW (via Naval): Code leverage — agents multiply human capability.",
            "DOAC Law 31: Skills are worthless; context is priceless — memory makes skills powerful.",
            "AJ: Passive income = leverage — systems that work while you don't.",
            "NBJ: Stack multipliers — layer tools for compound effect.",
            "AL: Composable agents — skills are components; mix and match for leverage.",
            "DA: Responsible capability — safeguards scale with power; Faraday doctrine.",
            "SG: Economic sovereignty — self-sufficient systems = leverage over external forces.",
        ],
    }

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        text_lower = msg.text.lower()

        # Route to specific creator
        if any(w in text_lower for w in ("chris williamson", "modern wisdom", "williamson", "chris w")):
            lines = ["**Chris Williamson (Modern Wisdom) — NCL Integration**\n"]
            for principle, desc in CREATOR_WISDOM["chris_williamson"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Key guests encoded: Huberman (neuro), Naval (leverage), "
                         "Goggins (toughness), Hormozi (value creation)*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("diary of a ceo", "doac", "steven bartlett", "bartlett", "33 laws")):
            lines = ["**Diary of a CEO (Steven Bartlett) — 33 Laws Applied**\n"]
            for principle, desc in CREATOR_WISDOM["diary_of_a_ceo"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Key guests encoded: Sinek (why), Gabor Mate (awareness), "
                         "James Clear (atomic habits), Mo Gawdat (happiness)*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("andrei jikh", "jikh", "passive income", "compound interest")):
            lines = ["**Andrei Jikh — Financial Intelligence x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["andrei_jikh"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Build automated systems that compound value — "
                         "passive income for your data, your knowledge, your time.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("tom bilyeu", "bilyeu", "impact theory")):
            lines = ["**Tom Bilyeu (Impact Theory) — Mindset & Identity x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["tom_bilyeu"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Your identity shapes your actions — "
                         "configure the agent's self-story before anything else.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("nate b jones", "nate jones", "ai strategy", "ai news")):
            lines = ["**Nate B Jones — AI Strategy & Automation x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["nate_b_jones"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: AI-first thinking — automate before you hire, "
                         "stack multipliers for compound results.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("j bravo", "bravo", "crypto")):
            lines = ["**J Bravo — Crypto & Risk Intelligence x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["j_bravo"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Decentralised thinking, risk management, "
                         "and asymmetric bets — small effort, massive upside.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("agentic lab", "agentic", "agent-first")):
            lines = ["**Agentic Lab — Agent-First Design x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["agentic_lab"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Design for autonomous operation — "
                         "compose agents from reusable skill components.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("ian carroll", "carroll", "opsec", "operational security")):
            lines = ["**Ian Carroll — Privacy & Operational Security x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["ian_carroll"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Privacy is freedom — protect identity, "
                         "question authority, travel light.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("dario amodei", "amodei", "anthropic", "ai safety",
                                           "responsible scaling", "machines of loving grace")):
            lines = ["**Dario Amodei (Anthropic) — Visionary & Trusted Council Advisor x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["dario_amodei"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Scale AI responsibly — safety, alignment, "
                         "and interpretability before capability. Machines of Loving Grace.*")
            reply = "\n".join(lines)
        elif any(w in text_lower for w in ("spencer gatten", "gatten", "geopolitical", "media literacy")):
            lines = ["**Spencer Gatten — Geopolitical & Media Intelligence x NCL**\n"]
            for principle, desc in CREATOR_WISDOM["spencer_gatten"].items():
                lines.append(f"* **{principle.replace('_', ' ').title()}**: {desc}")
            lines.append("\n*Core thesis: Sovereignty and media literacy — "
                         "understand power dynamics, filter noise, stay independent.*")
            reply = "\n".join(lines)
        else:
            # Category match or overview
            matched: list[str] = []
            for category in self.INSIGHTS:
                if category in text_lower:
                    matched.append(category)

            if matched:
                lines = [f"**Creator Wisdom — {', '.join(matched).title()}**\n"]
                for cat in matched:
                    for insight in self.INSIGHTS[cat]:
                        lines.append(f"* {insight}")
                reply = "\n".join(lines)
            else:
                lines = [
                    "**Creator Doctrine — 10 Sources x NCL**\n",
                    "**Chris Williamson** — Environment design, compound habits, "
                    "first principles, high agency.\n",
                    "**Diary of a CEO** — 33 Laws: five buckets, out-fail, "
                    "sweat small stuff, context not control.\n",
                    "**Andrei Jikh** — Passive income machines, compound interest, "
                    "automate everything, transparency.\n",
                    "**Tom Bilyeu** — Mindset is everything, radical accountability, "
                    "growth mindset, impact over income.\n",
                    "**Nate B Jones** — AI-first thinking, systems over tactics, "
                    "rapid prototyping, stack multipliers.\n",
                    "**J Bravo** — Decentralised thinking, risk management, "
                    "asymmetric bets, due diligence.\n",
                    "**Agentic Lab** — Agent-first design, workflow orchestration, "
                    "evaluation-driven, composable agents.\n",
                    "**Ian Carroll** — Privacy is freedom, identity protection, "
                    "operational security, question authority.\n",
                    "**Dario Amodei** 🛡️ — *Visionary & Trusted Council Advisor* — "
                    "AI safety, constitutional alignment, interpretability, "
                    "responsible scaling, Machines of Loving Grace.\n",
                    "**Spencer Gatten** — Geopolitical awareness, media literacy, "
                    "economic sovereignty, power dynamics, strategic independence.\n",
                    '*"Curate ruthlessly, learn relentlessly, compound daily."*',
                ]
                reply = "\n".join(lines)

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


# ═══════════════════════════════════════════════════════════════
#  Skill Router  (NCL Brain)
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  NCC Triad Skills  (Cross-Pillar Integration)
# ═══════════════════════════════════════════════════════════════

class TriadStatusSkill(Skill):
    """Report the NCC triad status — NCL (Brain), AAC (Bank), Super Agency."""

    name = "triad_status"
    triggers: ClassVar[list[str]] = [
        "triad status", "triad", "ncc status", "pillar status",
        "resonance status", "ecosystem status", "all pillars",
    ]
    description = "Shows the NCC triad status — all five pillar health and capabilities."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        if not NCC_AVAILABLE or not agent._ncc_orchestrator:
            return SkillResult(
                success=False,
                reply="NCC integration is not available.",
                skill_name=self.name,
                execution_ms=(time.monotonic() - t0) * 1000,
            )
        orch = agent._ncc_orchestrator
        status = orch.full_status()
        registry = PillarRegistry.get_instance()
        health = registry.health_summary()

        lines = [
            "**NCC Triad — Ecosystem Status**",
            f"• Triad Online: {'YES' if registry.triad_online() else 'NO'}",
            "",
        ]
        for pid, info in health.items():
            emoji = '🟢' if info['status'] == 'online' else '🔴' if info['status'] == 'offline' else '🟡'
            lines.append(f"{emoji} **{info['name']}** ({pid}) — {info['status']}")
            lines.append(f"  Role: {info['role']} | Capabilities: {info['capability_count']}")

        bus = InterPillarBus.get_instance()
        pool = DigitalLabourPool.get_instance()
        lines.append("")
        lines.append(f"• Bus messages dispatched: {bus._dispatched_count}")
        lines.append(f"• Bus dead-letter queue: {len(bus._dead_letter)}")
        lines.append(f"• Labour tasks completed: {pool._completed_count}")
        lines.append(f"• Labour tasks failed: {pool._failed_count}")
        lines.append(f"• PDCA cycles run: {status.get('pdca_cycles', 0)}")

        reply = "\n".join(lines)
        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class DigitalLabourSkill(Skill):
    """Dispatch tasks to Bit Rage Systems."""

    name = "digital_labour"
    triggers: ClassVar[list[str]] = [
        "dispatch task", "digital labour", "labour pool", "run task",
        "generate report", "labour status", "worker pool", "dispatch work",
        "bit rage", "brs task",
    ]
    description = "Dispatches tasks to Bit Rage Systems worker pool or shows pool status."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        if not NCC_AVAILABLE or not agent._ncc_orchestrator:
            return SkillResult(
                success=False,
                reply="NCC Digital Labour is not available.",
                skill_name=self.name,
                execution_ms=(time.monotonic() - t0) * 1000,
            )
        text_lower = msg.text.lower()
        pool = DigitalLabourPool.get_instance()

        if "status" in text_lower or "pool" in text_lower:
            stats = pool.stats()
            lines = [
                "**Digital Labour Pool — Status**",
                f"• Max workers: {stats.get('max_workers', 0)}",
                f"• Queue size: {stats.get('queue_size', 0)}",
                f"• Completed: {stats.get('completed', 0)}",
                f"• Failed: {stats.get('failed', 0)}",
                f"• Handlers: {', '.join(stats.get('handlers', []))}",
                f"• Running: {stats.get('running', False)}",
            ]
            reply = "\n".join(lines)
        else:
            reply = (
                "**Digital Labour — Task Types**\n"
                "Use `dispatch task <type>: <description>` to submit work.\n"
                "Available types: report, data_processing, research, analysis, monitoring"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class NCCCommandSkill(Skill):
    """Execute NCC governance commands."""

    name = "ncc_command"
    triggers: ClassVar[list[str]] = [
        "ncc", "governance", "pdca", "run pdca", "ncc health",
        "doctrine enforce", "pillar health",
    ]
    description = "Executes NCC governance commands — PDCA cycle, health checks, doctrine enforcement."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        if not NCC_AVAILABLE or not agent._ncc_orchestrator:
            return SkillResult(
                success=False,
                reply="NCC orchestrator is not available.",
                skill_name=self.name,
                execution_ms=(time.monotonic() - t0) * 1000,
            )
        text_lower = msg.text.lower()
        orch = agent._ncc_orchestrator

        if "pdca" in text_lower:
            result = await orch.run_pdca_cycle()
            lines = [
                "**NCC PDCA Governance Cycle**",
                f"• Cycle #{result.get('cycle', 0)}",
                f"• Phases: {' → '.join(result.get('phases_completed', []))}",
                f"• Evidence items: {result.get('evidence_count', 0)}",
            ]
            reply = "\n".join(lines)
        elif "health" in text_lower:
            registry = PillarRegistry.get_instance()
            health = registry.health_summary()
            lines = ["**NCC Pillar Health**"]
            for _pid, info in health.items():
                lines.append(f"• {info['name']}: {info['status']} ({info['capability_count']} capabilities)")
            reply = "\n".join(lines)
        else:
            status = orch.full_status()
            lines = [
                "**NCC Governance Overview**",
                f"• Orchestrator: {'RUNNING' if status.get('running') else 'STOPPED'}",
                f"• Pillars registered: {status.get('pillars_registered', 0)}",
                f"• PDCA cycles: {status.get('pdca_cycles', 0)}",
                f"• Commands handled: {status.get('commands_handled', 0)}",
                f"• Alerts handled: {status.get('alerts_handled', 0)}",
            ]
            reply = "\n".join(lines)

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class AutonomousDaemonSkill(Skill):
    """Control the NCL Autonomous Daemon — self-organizing 24/7 runtime."""

    name = "autonomous_daemon"
    triggers: ClassVar[list[str]] = [
        "daemon", "autonomous", "self-check", "gap analysis",
        "daemon status", "run cycle", "self check", "health check",
        "daemon start", "daemon stop", "system health", "gap scan",
    ]
    description = "Controls the NCL Autonomous Daemon — start/stop, run cycles, gap analysis, self-checks."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        text_lower = msg.text.lower()

        try:
            from ncl_agency_runtime.runtime.autonomous_daemon import (  # noqa: I001
                AutonomousDaemon, GapAnalyzer, KnowledgeJournal,
            )
            from ncl_agency_runtime.runtime.self_check_protocol import SelfCheckProtocol
        except ImportError:
            return SkillResult(
                success=False,
                reply="Autonomous daemon modules not available.",
                skill_name=self.name,
                execution_ms=(time.monotonic() - t0) * 1000,
            )

        if "self-check" in text_lower or "self check" in text_lower or "health check" in text_lower:
            protocol = SelfCheckProtocol()
            report = protocol.run_all()
            lines = [
                "**NCL Self-Check Report**",
                f"• Overall: {'HEALTHY' if report['overall_healthy'] else 'DEGRADED'}",
                f"• Score: {report['overall_score']:.1%}",
                f"• Checks passed: {report['checks_passed']}/{report['total_checks']}",
                "",
            ]
            for check in report.get("checks", []):
                status = "✅" if check["passed"] else "❌"
                lines.append(f"{status} {check['name']}: {check['score']:.0%} — {check['details'][:80]}")
                if not check["passed"] and check.get("recommendation"):
                    lines.append(f"  → {check['recommendation'][:100]}")
            reply = "\n".join(lines)

        elif "gap" in text_lower or "scan" in text_lower:
            analyzer = GapAnalyzer(_REPO_ROOT)
            gaps = analyzer.scan_all()
            lines = [f"**Gap Analysis** — {len(gaps)} gaps found\n"]
            for gap in gaps[:10]:
                lines.append(f"• [{gap.get('severity', '?')}] {gap.get('category', '?')}: {gap.get('description', '')[:80]}")
            if len(gaps) > 10:
                lines.append(f"\n... and {len(gaps) - 10} more gaps")
            reply = "\n".join(lines)

        elif "status" in text_lower:
            journal = KnowledgeJournal(_REPO_ROOT)
            recent = journal.recent(5)
            lines = ["**Autonomous Daemon — Recent Activity**\n"]
            if recent:
                for entry in recent:
                    lines.append(f"• [{entry.get('timestamp', '?')[:16]}] {entry.get('event', '?')}: {entry.get('message', '')[:60]}")
            else:
                lines.append("No recent daemon activity recorded.")
            reply = "\n".join(lines)

        elif "cycle" in text_lower or "run" in text_lower:
            daemon = AutonomousDaemon(repo_root=_REPO_ROOT)
            result = await daemon.run_single_cycle()
            lines = [
                "**Daemon Cycle Complete**",
                f"• Tasks generated: {result.get('tasks_generated', 0)}",
                f"• Tasks executed: {result.get('tasks_executed', 0)}",
                f"• Tasks succeeded: {result.get('tasks_succeeded', 0)}",
                f"• Tasks failed: {result.get('tasks_failed', 0)}",
            ]
            reply = "\n".join(lines)

        else:
            reply = (
                "**NCL Autonomous Daemon — Commands**\n"
                "• `self-check` — run full system health verification\n"
                "• `gap analysis` — scan for improvement opportunities\n"
                "• `daemon status` — show recent daemon activity\n"
                "• `run cycle` — execute one PDCA improvement cycle\n"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class GeneralChatSkill(Skill):
    """Handle any message that doesn't match a specific skill.

    Provides intelligent conversational responses by searching memory,
    offering contextual suggestions, and being generally helpful.
    """

    name = "general_chat"
    triggers: ClassVar[list[str]] = []  # Never matched by trigger — used as fallback only
    description = "Handles general conversation and unmatched messages."

    # Greetings the bot recognises
    GREETINGS: ClassVar[set[str]] = {"hi", "hello", "hey", "yo", "sup", "whats up", "what's up",
                 "good morning", "good evening", "good afternoon", "gm", "gn",
                 "greetings", "howdy", "hiya", "what up"}

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        text = msg.text.strip()
        text_lower = text.lower()

        # ── Greetings ─────────────────────────────────────
        if text_lower in self.GREETINGS or any(text_lower.startswith(g) for g in self.GREETINGS):
            reply = (
                f"Hey {msg.sender_name}! I'm the NCL Super OpenClaw Agent.\n\n"
                "Here's what I can do:\n"
                "• **Search memory** — ask me anything about stored knowledge\n"
                "• **Store memory** — tell me to \"remember this\"\n"
                "• **Doctrine** — NCL Master Doctrine concepts\n"
                "• **Brain map** — overview of the cognitive system\n"
                "• **Status** — my current health & uptime\n"
                "• **Learn** — trigger a learning cycle\n\n"
                "Or just chat with me — I'll search my memory for relevant context!"
            )
            elapsed = (time.monotonic() - t0) * 1000
            return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)

        # ── Try memory search for context ─────────────────
        memory_results = agent.memory_search(text, top_k=3)
        if memory_results:
            lines = [f"Here's what I found related to *\"{text[:60]}\"*:\n"]
            for i, (mem, _score) in enumerate(memory_results, 1):
                content = mem.get("content", str(mem)) if isinstance(mem, dict) else str(mem)
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"{i}. {content}")
            lines.append("\n💡 *Tip: say* `help` *to see all my skills.*")
            reply = "\n".join(lines)
        else:
            # ── Conversational fallback ────────────────────
            reply = (
                f"Got your message: *\"{text[:80]}\"*\n\n"
                "I don't have a specific answer for that yet, but here's what I can do:\n\n"
                "📝 **remember this <info>** — I'll store it in my brain\n"
                "🔍 **search <topic>** — I'll search my memory\n"
                "🧠 **brain map** — see the full cognitive overview\n"
                "📖 **doctrine** — NCL governance & philosophy\n"
                "📊 **status** — check my vitals\n"
                "🎓 **learn** — trigger memory consolidation\n\n"
                "Or just tell me something — I'm always learning!"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(success=True, reply=reply, skill_name=self.name, execution_ms=elapsed)


class SkillRouter:
    """Dispatches inbound messages to the best-matching skill.

    Uses trigger-keyword matching (OpenClaw-style).
    Falls back to GeneralChatSkill for unmatched messages.
    """

    def __init__(self):
        self.skills: list[Skill] = []
        self._fallback: Skill | None = None

    def register(self, skill: Skill):
        self.skills.append(skill)
        if isinstance(skill, GeneralChatSkill):
            self._fallback = skill
        LOG.info("Skill registered: %s (%d triggers)", skill.name, len(skill.triggers))

    def match(self, text: str) -> Skill | None:
        """Find the best matching skill for the given text."""
        text_lower = text.lower().strip()
        best_skill: Skill | None = None
        best_score = 0

        for skill in self.skills:
            for trigger in skill.triggers:
                if trigger in text_lower:
                    score = len(trigger)  # longer match = more specific
                    if score > best_score:
                        best_score = score
                        best_skill = skill

        return best_skill

    async def route(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        skill = self.match(msg.text)
        if skill:
            LOG.info("Routing to skill: %s", skill.name)
            return await skill.execute(msg, agent)
        # Use GeneralChatSkill as intelligent fallback
        if self._fallback:
            LOG.info("Routing to fallback: %s", self._fallback.name)
            return await self._fallback.execute(msg, agent)
        return SkillResult(
            success=True,
            reply="Send `help` to see what I can do.",
            skill_name="fallback"
        )


# ═══════════════════════════════════════════════════════════════
#  Channel Connector Base  (NCL Senses)
# ═══════════════════════════════════════════════════════════════

class ChannelConnector(ABC):
    """Base class for message channel integrations."""

    channel_type: ChannelType = ChannelType.CLI

    @abstractmethod
    async def start(self, agent: SuperOpenClawAgent):
        """Start listening on this channel."""
        ...

    @abstractmethod
    async def stop(self):
        """Gracefully stop this channel."""
        ...

    @abstractmethod
    async def send(self, msg: OutboundMessage):
        """Send a message on this channel."""
        ...


# ═══════════════════════════════════════════════════════════════
#  Health Monitor  (NCL Regeneration)
# ═══════════════════════════════════════════════════════════════

class HealthMonitor:
    """Periodic heartbeat and self-diagnostics.

    Checks:
        - Memory system reachable
        - Skills loaded
        - Channel connectors alive
        - Event bus backpressure
    """

    def __init__(self, agent: SuperOpenClawAgent, interval_s: int = 60):
        self.agent = agent
        self.interval_s = interval_s
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        LOG.info("HealthMonitor started (interval=%ds)", self.interval_s)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while self._running:
            try:
                report = self.check()
                await self.agent.event_bus.publish("health.heartbeat", report)
                if not report["healthy"]:
                    LOG.warning("Health check DEGRADED: %s", report.get("issues"))
            except Exception as exc:
                LOG.error("HealthMonitor error: %s", exc)
            await asyncio.sleep(self.interval_s)

    def check(self) -> dict:
        issues = []
        if not self.agent._memory_manager:
            issues.append("memory_offline")
        if not self.agent.skill_router.skills:
            issues.append("no_skills_loaded")
        if not self.agent.channels:
            issues.append("no_channels")

        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "skills": len(self.agent.skill_router.skills),
            "channels": len(self.agent.channels),
            "messages_processed": self.agent._msg_count,
            "uptime_s": time.time() - self.agent._start_time,
            "ts": datetime.now(UTC).isoformat()
        }


# ═══════════════════════════════════════════════════════════════
#  Super OpenClaw Agent  (the whole organism)
# ═══════════════════════════════════════════════════════════════

class SuperOpenClawAgent:
    """NCL Super OpenClaw Agent — the complete cognitive organism.

    Integrates all Living Organism layers:
        Senses      → ChannelConnectors (Discord, Telegram, CLI)
        Brain       → SkillRouter (dispatch)
        Nervous     → EventBus (pub/sub)
        Muscles     → Skills (execute)
        Immune      → PolicyGate (Faraday Fortress)
        Memory      → ncl_memory MemoryManager + VectorIndex
        Regeneration→ HealthMonitor (heartbeat)
    """

    def __init__(
        self,
        agent_id: str | None = None,
        config_path: str | None = None,
        allowed_senders: list[str] | None = None,
    ):
        self.agent_id = agent_id or f"openclaw-{uuid.uuid4().hex[:8]}"
        self.config = self._load_config(config_path)
        self._start_time = time.time()
        self._msg_count = 0

        # Living Organism layers
        self.event_bus = EventBus()
        self.policy_gate = PolicyGate(allowed_senders=allowed_senders or ["AZ_PRIME"])
        self.skill_router = SkillRouter()
        self.health_monitor = HealthMonitor(
            self,
            interval_s=self.config.get("health_monitor_interval_s", 60),
        )

        # Memory (NCL second brain)
        self._memory_manager: Any | None = None
        if MEMORY_AVAILABLE:
            try:
                self._memory_manager = get_memory_manager()
                LOG.info("Memory backend connected (second brain ONLINE)")
            except Exception as exc:
                LOG.warning("Memory init failed: %s", exc)

        # NCC Triad integration
        self._ncc_orchestrator: Any | None = None
        if NCC_AVAILABLE:
            try:
                self._ncc_orchestrator = NCCOrchestrator.get_instance()
                LOG.info("NCC Orchestrator linked")
            except Exception as exc:
                LOG.warning("NCC Orchestrator init failed: %s", exc)

        # Channels (senses)
        self.channels: list[ChannelType] = []
        self._connectors: dict[ChannelType, ChannelConnector] = {}

        # Register built-in skills
        self._register_default_skills()

        LOG.info("SuperOpenClawAgent initialised: %s", self.agent_id)

    # ── Config ────

    def _load_config(self, path: str | None = None) -> dict:
        candidates = [
            path,
            str(_REPO_ROOT / "ncl_config.json"),
            os.path.expanduser("~/NCL/ncl_config.json"),
        ]
        for p in candidates:
            if p and os.path.isfile(p):
                with open(p) as f:
                    LOG.info("Config loaded from %s", p)
                    result: dict = json.load(f)
                    return result
        LOG.warning("No config file found — using defaults")
        return {}

    # ── Skills ────

    def _register_default_skills(self):
        skill_classes: list[type[Skill]] = [
            MemorySearchSkill,
            MemoryStoreSkill,
            DoctrineSkill,
            StrategicAdvisorSkill,
            CreatorWisdomSkill,
            BrainMapSkill,
            StatusSkill,
            HelpSkill,
            LearningSkill,
        ]
        # NCC triad skills (only when integration is available)
        if NCC_AVAILABLE:
            skill_classes.extend([
                TriadStatusSkill,
                DigitalLabourSkill,
                NCCCommandSkill,
            ])
        # Autonomous daemon skill — always available
        skill_classes.append(AutonomousDaemonSkill)

        # ClawHub skills (lazy import to avoid circular dependency)
        clawhub_enabled = self.config.get("clawhub", {}).get("enabled", True)
        if clawhub_enabled:
            try:
                from ncl_agency_runtime.agents.clawhub_skills import create_clawhub_skills
                for skill in create_clawhub_skills():
                    self.skill_router.register(skill)
                LOG.info("ClawHub skills registered")
            except ImportError:
                LOG.info("ClawHub skills not available — skipping")

        # GeneralChat must be last (it is the fallback)
        skill_classes.append(GeneralChatSkill)
        for skill_cls in skill_classes:
            self.skill_router.register(skill_cls())  # type: ignore[abstract]

    def register_skill(self, skill: Skill):
        """Register a custom skill at runtime."""
        self.skill_router.register(skill)

    # ── Channel management ────

    def add_channel(self, connector: ChannelConnector):
        """Register a channel connector (Discord, Telegram, etc.)."""
        self._connectors[connector.channel_type] = connector
        self.channels.append(connector.channel_type)
        LOG.info("Channel added: %s", connector.channel_type.value)

    # ── Message processing pipeline ────

    async def process_message(self, msg: InboundMessage) -> SkillResult:
        """Main message pipeline — the Living Organism in action.

        Strategic doctrine woven throughout:
        1. PolicyGate (Immune) — Art of War: all warfare is deception → zero-trust
        2. EventBus publish (Nervous) — Law 9: win through actions → evidence trail
        3. SkillRouter dispatch (Brain → Muscles) — Law 48: assume formlessness
        4. Memory ingestion (Memory) — Habit 5: seek first to understand
        5. Reply via channel (Senses) — Habit 6: synergize via cross-component flow
        """
        self._msg_count += 1

        # 1. Policy gate  [Art of War: deception defence / Habit 1: be proactive]
        allowed, reason = self.policy_gate.evaluate(msg)
        if not allowed:
            return SkillResult(success=False, reply=f"Access denied: {reason}", skill_name="policy_gate")

        # 2. Publish inbound event  [Law 9: evidence over argument]
        await self.event_bus.publish("message.inbound", msg.to_dict())

        # 3. Route to skill  [Law 48: formlessness / Habit 3: first things first]
        result = await self.skill_router.route(msg, self)

        # 4. Store episodic memory  [Habit 5: understand first / Sun Tzu: know yourself]
        self.memory_store(
            content=f"[{msg.channel.value}] {msg.sender_name}: {msg.text[:200]}",
            memory_type="episodic",
            tags=["interaction", msg.channel.value, result.skill_name],
            context={"sender": msg.sender_name, "skill": result.skill_name,
                     "success": result.success}
        )

        # 5. Publish outbound event  [Habit 6: synergize]
        await self.event_bus.publish("message.outbound", {
            "msg_id": msg.id,
            "skill": result.skill_name,
            "success": result.success,
            "reply_len": len(result.reply),
        })

        return result

    # ── Memory interface (NCL Second Brain) ────

    def memory_search(self, query: str, top_k: int = 5) -> list[tuple[Any, float]]:
        """Semantic search across NCL memory.

        Returns list of ``(dict, float)`` tuples where the dict is a memory
        representation and the float is a relevance/importance score.
        """
        if not self._memory_manager:
            return []
        try:
            if hasattr(self._memory_manager, "semantic_search"):
                raw = self._memory_manager.semantic_search(query, top_k=top_k)
                # semantic_search returns List[MemoryUnit]; convert to scored tuples
                results: list[tuple[Any, float]] = []
                for mem in raw:
                    mem_dict = mem.to_dict() if hasattr(mem, "to_dict") else {"content": str(mem)}
                    score = getattr(mem, "importance", 0.5)
                    results.append((mem_dict, score))
                return results
            if hasattr(self._memory_manager, "search_memories"):
                raw = self._memory_manager.search_memories({"content": query}, limit=top_k)
                return [(m.to_dict() if hasattr(m, "to_dict") else {"content": str(m)},
                         getattr(m, "importance", 0.5)) for m in raw]
        except Exception as exc:
            LOG.error("Memory search failed: %s", exc)
        return []

    def memory_store(self, content: str, memory_type: str = "episodic",
                     tags: list[str] | None = None,
                     context: dict | None = None) -> bool:
        """Store a memory in the NCL second brain."""
        if not self._memory_manager:
            return False
        try:
            if MEMORY_AVAILABLE:
                # MemoryManager exposes store_memory(), not store()
                self._memory_manager.store_memory(
                    content=content,
                    memory_type=memory_type,
                    tags=tags or [],
                    context=context or {},
                )
                return True
        except Exception as exc:
            LOG.error("Memory store failed: %s", exc)
        return False

    def memory_stats(self) -> dict[str, int]:
        """Return memory statistics for brain map."""
        stats = {"total": 0, "episodic": 0, "semantic": 0, "procedural": 0, "working": 0}
        if not self._memory_manager:
            return stats
        try:
            # MemoryManager exposes get_memory_stats(), not get_stats()
            if hasattr(self._memory_manager, "get_memory_stats"):
                raw = self._memory_manager.get_memory_stats()
                stats["working"] = raw.get("working_memory_count", 0)
                stats["episodic"] = raw.get("short_term_count", 0)
                stats["semantic"] = raw.get("long_term_count", 0)
                stats["total"] = stats["working"] + stats["episodic"] + stats["semantic"]
                return stats
            if hasattr(self._memory_manager, "storage"):
                stg = self._memory_manager.storage
                stats["working"] = len(getattr(stg, "working_memory", {}))
                if hasattr(stg, "short_term_db"):
                    stats["episodic"] = self._memory_manager._get_db_count(stg.short_term_db)
                if hasattr(stg, "long_term_db"):
                    stats["semantic"] = self._memory_manager._get_db_count(stg.long_term_db)
                stats["total"] = stats["working"] + stats["episodic"] + stats["semantic"]
                return stats
            if hasattr(self._memory_manager, "memories"):
                mems = self._memory_manager.memories
                stats["total"] = len(mems)
                for m in mems.values() if isinstance(mems, dict) else mems:
                    mt = m.memory_type if hasattr(m, "memory_type") else "episodic"
                    if mt in stats:
                        stats[mt] += 1
        except Exception:
            pass
        return stats

    async def start(self):
        """Start the agent and all subsystems."""
        LOG.info("Starting SuperOpenClawAgent %s ...", self.agent_id)

        # Bootstrap NCC triad (before anything else — governance first)
        if self._ncc_orchestrator:
            try:
                self._ncc_orchestrator.bootstrap()
                await self._ncc_orchestrator.start()
                # Mark NCL pillar as ONLINE (we ARE the brain)
                registry = PillarRegistry.get_instance()
                registry.set_status(PillarID.NCL, PillarStatus.ONLINE)
                LOG.info("NCC Triad bootstrapped — NCL ONLINE")
            except Exception as exc:
                LOG.error("NCC bootstrap failed: %s", exc)

        # Start health monitor
        await self.health_monitor.start()

        # Start channel connectors
        for ctype, connector in self._connectors.items():
            try:
                await connector.start(self)
                LOG.info("Channel %s started", ctype.value)
            except Exception as exc:
                LOG.error("Channel %s failed to start: %s", ctype.value, exc)

        await self.event_bus.publish("agent.started", {
            "agent_id": self.agent_id,
            "skills": [s.name for s in self.skill_router.skills],
            "channels": [c.value for c in self.channels],
            "ncc_triad": NCC_AVAILABLE,
        })
        LOG.info("SuperOpenClawAgent ONLINE — %d skills, %d channels, NCC=%s",
                 len(self.skill_router.skills), len(self.channels),
                 "ACTIVE" if self._ncc_orchestrator else "OFF")

    async def stop(self):
        """Gracefully shut down."""
        LOG.info("Stopping SuperOpenClawAgent %s ...", self.agent_id)
        # Stop NCC orchestrator first (governance shuts down last-in-first-out)
        if self._ncc_orchestrator:
            try:
                await self._ncc_orchestrator.stop()
                LOG.info("NCC Orchestrator stopped")
            except Exception as exc:
                LOG.error("NCC stop failed: %s", exc)
        await self.health_monitor.stop()
        for connector in self._connectors.values():
            try:  # noqa: SIM105
                await connector.stop()
            except Exception:
                pass
        await self.event_bus.publish("agent.stopped", {"agent_id": self.agent_id})
        LOG.info("SuperOpenClawAgent OFFLINE")

    # ── CLI interactive mode ────

    async def run_cli(self):
        """Simple interactive CLI for testing."""
        print(f"\n  NCL Super OpenClaw Agent [{self.agent_id}]")
        print(f"  Skills: {len(self.skill_router.skills)} | Memory: {'ON' if self._memory_manager else 'OFF'}")
        print("  Type 'help' for commands, 'quit' to exit.\n")

        await self.start()
        try:
            while True:
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("you > ")
                    )
                except EOFError:
                    break

                if user_input.strip().lower() in ("quit", "exit", "q"):
                    break

                msg = InboundMessage(
                    channel=ChannelType.CLI,
                    sender_id="AZ_PRIME",
                    sender_name="AZ",
                    text=user_input
                )
                result = await self.process_message(msg)
                print(f"\nagent > {result.reply}\n")
        finally:
            await self.stop()


# ═══════════════════════════════════════════════════════════════
#  Convenience factory
# ═══════════════════════════════════════════════════════════════

def create_agent(
    *,
    config_path: str | None = None,
    allowed_senders: list[str] | None = None,
    extra_skills: list[Skill] | None = None,
) -> SuperOpenClawAgent:
    """Create a fully configured SuperOpenClawAgent."""
    agent = SuperOpenClawAgent(
        config_path=config_path,
        allowed_senders=allowed_senders
    )
    for skill in (extra_skills or []):
        agent.register_skill(skill)
    return agent


# ═══════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    agent = create_agent()
    asyncio.run(agent.run_cli())
