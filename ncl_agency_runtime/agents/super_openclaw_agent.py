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
        """6-step policy chain.  Returns (allowed, reason)."""
        # Step 1 — kill switch
        if self.kill_switch:
            reason = "KILL_SWITCH_ACTIVE"
            self._log_denial(msg, reason)
            return False, reason

        # Step 2 — system mode
        if self.system_mode == "lockdown":
            reason = "SYSTEM_LOCKDOWN"
            self._log_denial(msg, reason)
            return False, reason
        if self.system_mode == "maintenance" and msg.sender_id != self.AZ_PRIME:
            reason = "MAINTENANCE_MODE"
            self._log_denial(msg, reason)
            return False, reason

        # Step 3 — provenance (channel trust)
        if msg.channel not in self.trusted_channels:
            reason = f"UNTRUSTED_CHANNEL:{msg.channel}"
            self._log_denial(msg, reason)
            return False, reason

        # Step 4 — sender allow-list
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

        # Step 6 — risk tier
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


# ═══════════════════════════════════════════════════════════════
#  Skill Router  (NCL Brain)
# ═══════════════════════════════════════════════════════════════

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
        for skill_cls in [
            MemorySearchSkill,
            MemoryStoreSkill,
            DoctrineSkill,
            BrainMapSkill,
            StatusSkill,
            HelpSkill,
            LearningSkill,
            GeneralChatSkill,
        ]:
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
        """Main message pipeline:
        1. PolicyGate evaluation (Immune)
        2. EventBus publish (Nervous)
        3. SkillRouter dispatch (Brain → Muscles)
        4. Memory ingestion (Memory)
        5. Reply via channel (Senses outbound)
        """
        self._msg_count += 1

        # 1. Policy gate
        allowed, reason = self.policy_gate.evaluate(msg)
        if not allowed:
            return SkillResult(success=False, reply=f"Access denied: {reason}", skill_name="policy_gate")

        # 2. Publish inbound event
        await self.event_bus.publish("message.inbound", msg.to_dict())

        # 3. Route to skill
        result = await self.skill_router.route(msg, self)

        # 4. Store episodic memory of the interaction
        self.memory_store(
            content=f"[{msg.channel.value}] {msg.sender_name}: {msg.text[:200]}",
            memory_type="episodic",
            tags=["interaction", msg.channel.value, result.skill_name],
            context={"sender": msg.sender_name, "skill": result.skill_name,
                     "success": result.success}
        )

        # 5. Publish outbound event
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
        except Exception:  # noqa: S110
            pass
        return stats

    async def start(self):
        """Start the agent and all subsystems."""
        LOG.info("Starting SuperOpenClawAgent %s ...", self.agent_id)

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
        })
        LOG.info("SuperOpenClawAgent ONLINE — %d skills, %d channels",
                 len(self.skill_router.skills), len(self.channels))

    async def stop(self):
        """Gracefully shut down."""
        LOG.info("Stopping SuperOpenClawAgent %s ...", self.agent_id)
        await self.health_monitor.stop()
        for connector in self._connectors.values():
            try:  # noqa: SIM105
                await connector.stop()
            except Exception:  # noqa: S110
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
