"""Main NCL brain service."""

import asyncio
import json
import logging
import os
import re
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiofiles
import httpx


# ---------------------------------------------------------------------------
# Config validation — fail fast on missing required env vars
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS = [
    "CLAUDE_API_KEY",
]

_OPTIONAL_BUT_WARNED_ENV_VARS = [
    "NCC_HOST",
    "NCC_PORT",
]


def _validate_config() -> None:
    """Validate required environment variables exist at import time."""
    missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            f"NCL Brain startup failed — missing required env vars: {', '.join(missing)}. "
            f"Set them before starting the service."
        )
    for v in _OPTIONAL_BUT_WARNED_ENV_VARS:
        if not os.getenv(v):
            logging.getLogger("ncl.brain").warning(
                f"[config] Optional env var {v} not set — using defaults"
            )


_validate_config()

log = logging.getLogger("ncl.brain")

from .models import (
    PumpPrompt,
    Mandate,
    MandateStatus,
    CouncilSession,
    CouncilMember,
    FeedbackReport,
    PillarType,
    InsightSignal,
    NCLEvent,
)
from .council import CouncilEngine
from ..memory import MemoryStore
from ..awarebot import Scanner, FuturePredictor
from ..paperclip_adapter import PaperclipClient
from ..swarm.orchestrator import SwarmOrchestrator
from ..swarm.llm_router import LLMRouter
from ..swarm.blackboard import Blackboard


# Keys/values redacted from log payloads and persisted events.
_REDACT_KEYS = {
    "api_key",
    "apikey",
    "bearer",
    "token",
    "access_token",
    "secret",
    "password",
    "claude_api_key",
    "anthropic_api_key",
    "openai_api_key",
    "xai_api_key",
    "google_api_key",
    "perplexity_api_key",
    "copilot_api_key",
    "x_bearer_token",
    "youtube_api_key",
    "reddit_client_secret",
    "strike_auth_token",
    "authorization",
}


def _redact(payload):
    """Recursively redact sensitive keys from a dict/list payload."""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if isinstance(k, str) and k.lower() in _REDACT_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(payload, list):
        return [_redact(item) for item in payload]
    return payload


# ── Shared HTTP Client for brain outbound calls ─────────────────────────
# Reused across budget policies, NCC dispatch, and ntfy notifications
# to avoid connection pool exhaustion from per-request client creation.

_brain_http_client: Optional[httpx.AsyncClient] = None
_brain_http_lock: Optional[asyncio.Lock] = None


def _get_brain_http_lock() -> asyncio.Lock:
    global _brain_http_lock
    if _brain_http_lock is None:
        _brain_http_lock = asyncio.Lock()
    return _brain_http_lock


async def _get_brain_http_client() -> httpx.AsyncClient:
    """Return a shared HTTP client for NCL Brain outbound calls."""
    global _brain_http_client
    if _brain_http_client is None or _brain_http_client.is_closed:
        async with _get_brain_http_lock():
            if _brain_http_client is None or _brain_http_client.is_closed:
                _brain_http_client = httpx.AsyncClient(timeout=30.0)
    return _brain_http_client


async def close_brain_http_client() -> None:
    """Close the shared HTTP client (call on shutdown)."""
    global _brain_http_client
    if _brain_http_client is not None:
        await _brain_http_client.aclose()
        _brain_http_client = None


class NCLBrain:
    """
    The NCL brain - NCL runtime service.

    Receives pump prompts, spawns council sessions, produces mandates,
    manages memory, integrates with Awarebot, and coordinates with Paperclip.
    """

    def __init__(
        self,
        data_dir: str | Path,
        claude_api_key: str,
        anthropic_base_url: str = "https://api.anthropic.com",
        xai_api_key: Optional[str] = None,
        google_api_key: Optional[str] = None,
        perplexity_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        copilot_api_key: Optional[str] = None,
        x_bearer_token: Optional[str] = None,
        youtube_api_key: Optional[str] = None,
        reddit_client_id: Optional[str] = None,
        reddit_client_secret: Optional[str] = None,
        ollama_host: str = "localhost:11434",
        paperclip_host: str = "localhost",
        paperclip_port: int = 8787,
        policy_kernel: Optional[object] = None,
        emergency_stop: Optional[object] = None,
    ) -> None:
        """
        Initialize NCL brain.

        Args:
            data_dir: Data directory for state/events
            claude_api_key: Anthropic API key
            anthropic_base_url: Anthropic API base URL
            xai_api_key: xAI API key
            google_api_key: Google API key
            perplexity_api_key: Perplexity API key
            openai_api_key: OpenAI API key
            x_bearer_token: X API bearer token
            youtube_api_key: YouTube API key
            reddit_client_id: Reddit OAuth client ID
            reddit_client_secret: Reddit OAuth client secret
            ollama_host: Ollama server host:port
            paperclip_host: Paperclip server hostname
            paperclip_port: Paperclip server port
        """
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Event log and state files
        self.events_file = self.data_dir / "events.ndjson"
        self.mandates_file = self.data_dir / "mandates.json"
        self.state_file = self.data_dir / "state.json"
        self._pending_dispatches_file = self.data_dir / "pending_dispatches.json"

        # Event log rotation: rotate events.ndjson when it exceeds 100 MB
        self._events_file_max_bytes = 100 * 1024 * 1024  # 100 MB
        self._events_rotate_backups = 5

        # Initialize Paperclip first (needed by council engine)
        _pc_base = f"http://{paperclip_host}:{paperclip_port}" if paperclip_host else None
        self.paperclip = PaperclipClient(
            base_url=_pc_base,
        )

        # Initialize subsystems
        self.council_engine = CouncilEngine(
            claude_api_key=claude_api_key,
            anthropic_base_url=anthropic_base_url,
            xai_api_key=xai_api_key,
            google_api_key=google_api_key,
            perplexity_api_key=perplexity_api_key,
            openai_api_key=openai_api_key,
            copilot_api_key=copilot_api_key,
            ollama_host=ollama_host,
            paperclip_client=self.paperclip,  # Inject Paperclip into council
        )

        self.memory_store = MemoryStore(self.data_dir)

        self.scanner = Scanner(
            x_bearer_token=x_bearer_token,
            youtube_api_key=youtube_api_key,
            reddit_client_id=reddit_client_id,
            reddit_client_secret=reddit_client_secret,
        )

        self.predictor = FuturePredictor(
            claude_api_key=claude_api_key,
            anthropic_base_url=anthropic_base_url,
            ollama_host=ollama_host,
        )

        # MWP output directories for stage handoffs (Jake Van Clief protocol)
        self.mwp_base = Path(data_dir).expanduser().parent / "workspaces" / "mandate-generation" / "stages"

        # In-memory state (bounded collections to prevent unbounded growth)
        self.mandates: dict[str, Mandate] = {}
        self._mandates_lock = asyncio.Lock()
        self.council_sessions: OrderedDict[str, CouncilSession] = OrderedDict()
        self._council_sessions_lock = asyncio.Lock()  # Guards council_sessions dict
        self._COUNCIL_SESSIONS_MAX = 50  # Evict oldest completed sessions when full
        self._pending_dispatches: OrderedDict[str, dict] = OrderedDict()  # pump_id → pending approval data
        self._PENDING_DISPATCHES_MAX = 200
        self._pending_dispatches_lock = asyncio.Lock()  # Guards _pending_dispatches reads/writes

        # Governance hooks (optional — graceful degradation when None)
        self.policy_kernel = policy_kernel
        self.emergency_stop = emergency_stop

        # Agent Swarm — multi-LLM task execution engine
        _swarm_config = {
            "anthropic_api_key": claude_api_key,
            "xai_api_key": xai_api_key or "",
            "google_api_key": google_api_key or "",
            "openai_api_key": openai_api_key or "",
            "perplexity_api_key": perplexity_api_key or "",
            "ollama_host": ollama_host,
        }
        self._swarm_llm_router = LLMRouter(config=_swarm_config)
        self._swarm_blackboard = Blackboard(persist_path=self.data_dir / "swarm" / "blackboard.json")
        self.swarm = SwarmOrchestrator(
            config=_swarm_config,
            llm_router=self._swarm_llm_router,
            blackboard=self._swarm_blackboard,
            policy_kernel=policy_kernel,
            emergency_stop=emergency_stop,
        )

        # Research cortex (injected by routes.py at startup to avoid circular imports)
        self.research_cortex = None

        # Process start time (for real uptime reporting in health_check)
        self._started_at: Optional[datetime] = None

    async def init(self) -> None:
        """Initialize brain on startup."""
        self._started_at = datetime.now(timezone.utc)
        # Load existing state
        await self._load_state()
        await self._load_pending_dispatches()

        # Start periodic cleanup for zombie council sessions (every 15 min)
        self._cleanup_task = asyncio.create_task(self._periodic_council_cleanup())

        # Register with Paperclip (skip entirely if explicitly disabled)
        self._paperclip_connected = False
        if os.getenv("PAPERCLIP_HOST", "localhost") == "":
            log.info("Paperclip disabled (PAPERCLIP_HOST=\"\") \u2014 skipping registration")
            await self._log_event("startup", "NCL brain initialized, Paperclip disabled by config")
            return
        try:
            company_id = await self.paperclip.register_company()
            await self.paperclip.register_agent("NCL", "Think, Research, Plan, Decide", "brain")
            await self.paperclip.register_agent("UNI", "Research cortex", "research")
            await self.paperclip.register_agent("Awarebot-FPC", "Scanner + predictor", "intelligence")
            await self.paperclip.register_agent("Strategy", "Mandate generation", "strategy")
            await self.paperclip.register_agent("Memory", "Living context", "memory")

            # Set per-agent budget policies (from NCL contract: $1,070/month total)
            # NCL: 10% ($107), NCC: 30% ($321), BRS: 40% ($428), AAC: 20% ($214)
            await self._set_budget_policies()

            self._paperclip_connected = True
            log.info("NCL brain initialized — Paperclip connected, budgets set")
            await self._log_event("startup", "NCL brain initialized, Paperclip connected, budgets configured")
        except Exception as e:
            log.warning(f"Paperclip registration failed (non-fatal, will retry): {e}")
            await self._log_event("startup_warning", f"Paperclip unavailable: {e}")

    async def _set_budget_policies(self) -> None:
        """
        Set per-agent budget policies in Paperclip on startup.

        Budget allocation from NCL contract ($1,070/month total):
        - NCL agents: 10% ($107/month → 10700¢)
        - NCC (execution): 30% ($321/month → 32100¢)
        - BRS (revenue): 40% ($428/month → 42800¢)
        - AAC (capital): 20% ($214/month → 21400¢)

        Uses POST /api/companies/:companyId/budgets/policies
        """
        paperclip_url = os.getenv("PAPERCLIP_URL", "http://localhost:3100")
        company_id = os.getenv("PAPERCLIP_COMPANY_ID", "")
        if not company_id:
            log.warning("[budget] No PAPERCLIP_COMPANY_ID, skipping budget policies")
            return

        # Agent budgets (scopeType: "agent", amount in cents per month)
        agent_budgets = {
            "NCL": 10700,        # $107/month — brain operations
            "UNI": 5000,         # $50/month — research cortex
            "Awarebot-FPC": 3000,  # $30/month — scanner
            "Strategy": 2000,    # $20/month — mandate generation
            "Memory": 700,       # $7/month — context storage
        }

        client = await _get_brain_http_client()
        for agent_name, budget_cents in agent_budgets.items():
            try:
                resp = await client.post(
                    f"{paperclip_url}/api/companies/{company_id}/budgets/policies",
                    json={
                        "scopeType": "agent",
                        "scopeId": agent_name,
                        "amount": budget_cents,
                        "windowKind": "calendar_month",
                    },
                    timeout=10.0,
                )
                if resp.status_code < 400:
                    log.info(f"[budget] Set {agent_name} budget: {budget_cents}¢/month")
                else:
                    log.warning(f"[budget] Failed to set {agent_name} budget: {resp.status_code}")
            except Exception as e:
                log.warning(f"[budget] Budget policy error for {agent_name}: {e}")

    async def receive_pump_prompt(self, prompt: PumpPrompt, auto_flow: bool = True) -> dict:
        """
        Receive and process a pump prompt from iPhone.

        Full strike point flow (when auto_flow=True):
        1. Log + store in memory
        2. Spawn council session (Claude chairs debate)
        3. Extract mandates from council consensus
        4. Create mandates in Paperclip
        5. Dispatch to target pillars via NCC

        Args:
            prompt: PumpPrompt from Grok
            auto_flow: If True, runs full council → mandate → dispatch pipeline

        Returns:
            Dict with pump_id, council results, and generated mandates
        """
        await self._log_event(
            "pump_received",
            f"Pump from {prompt.source}: {prompt.intent}",
            {"pump_id": prompt.prompt_id, "urgency": prompt.urgency},
        )

        # Store in memory
        await self.memory_store.create_unit(
            content=f"Pump prompt: {prompt.intent}",
            source=f"pump:{prompt.source}",
            importance=60.0 if prompt.urgency == "critical" else 40.0,
            tags=["pump", prompt.source, prompt.urgency],
        )

        result: dict = {
            "pump_id": prompt.prompt_id,
            "intent": prompt.intent,
            "urgency": prompt.urgency,
        }

        if not auto_flow:
            return result

        # ---------------------------------------------------------------
        # STRIKE POINT AUTO-FLOW: Council → Mandate → Dispatch
        # MWP Stage Handoffs at each phase (Jake Van Clief protocol)
        # ---------------------------------------------------------------

        # MWP Stage 01 — Intake: write raw pump to output
        await self._mwp_intake(prompt)

        # Step 1: Build council prompt from pump context
        council_prompt = self._build_council_prompt(prompt)

        # MWP Stage 02 — Analysis: write council prompt + context
        await self._mwp_analysis(prompt, council_prompt)

        # Step 2: Spawn council session
        try:
            session = await self.spawn_council_session(
                topic=f"Pump: {prompt.intent}",
                prompt=council_prompt,
                members=None,  # Full council
            )
            result["council"] = {
                "session_id": session.session_id,
                "consensus": session.consensus,
                "recommendations": session.recommendations,
                "dissents": session.dissents,
            }
            await self._log_event(
                "strike_council_complete",
                f"Strike point council completed for pump {prompt.prompt_id}",
                {"session_id": session.session_id, "consensus": session.consensus},
            )
        except Exception as e:
            log.error(f"Council failed for pump {prompt.prompt_id}: {e}")
            result["council"] = {"error": str(e)}
            return result

        # MWP Stage 03 — Synthesis: write council transcript + consensus
        await self._mwp_synthesis(session)

        # Step 3: Extract mandates from council output
        mandates_data = self._extract_mandates_from_council(session, prompt)
        result["mandates"] = []

        # MWP Stage 04 — Mandate Draft: write extracted mandates
        await self._mwp_mandate_draft(mandates_data, prompt.prompt_id)

        # Step 4: Create mandates as PENDING_APPROVAL (NOT active — NATRIX reviews first)
        for md in mandates_data:
            try:
                mandate = await self.create_mandate(
                    pillar=md["pillar"],
                    priority=md["priority"],
                    title=md["title"],
                    objective=md["objective"],
                    success_criteria=md.get("success_criteria", []),
                    source_pump_id=prompt.prompt_id,
                    status=MandateStatus.PENDING_APPROVAL,
                )
                result["mandates"].append({
                    "mandate_id": mandate.mandate_id,
                    "pillar": mandate.pillar.value,
                    "title": mandate.title,
                    "priority": mandate.priority,
                    "objective": mandate.objective,
                    "success_criteria": mandate.success_criteria,
                })
            except Exception as e:
                log.error(f"Mandate creation failed: {e}")
                result["mandates"].append({"error": str(e), "title": md.get("title", "?")})

        # ---------------------------------------------------------------
        # STOP HERE — DO NOT DISPATCH TO NCC
        # NATRIX must review council output + proposed mandates first.
        # Call /pump/approve/{pump_id} to approve and dispatch.
        # ---------------------------------------------------------------

        # MWP Stage 05 — Review: write approval package for NATRIX
        await self._mwp_review(prompt, session, result["mandates"])

        # Store pump_id → mandate mapping for approval lookup
        async with self._pending_dispatches_lock:
            self._pending_dispatches[prompt.prompt_id] = {
                "mandates": result["mandates"],
                "council_session_id": session.session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            # Enforce bounded size
            while len(self._pending_dispatches) > self._PENDING_DISPATCHES_MAX:
                self._pending_dispatches.popitem(last=False)
            await self._persist_pending_dispatches_unlocked()

        result["status"] = "pending_approval"
        result["message"] = (
            "Council complete. Review proposed mandates above. "
            "Call /pump/approve/{pump_id} to approve and dispatch to NCC, "
            "or /pump/reject/{pump_id} to discard."
        )

        await self._log_event(
            "strike_pending_approval",
            f"Strike point awaiting NATRIX approval for pump {prompt.prompt_id}",
            {"mandates_proposed": len(result["mandates"])},
        )

        return result

    async def approve_and_dispatch(
        self,
        pump_id: str,
        approved_mandate_ids: list[str] | None = None,
        modifications: dict[str, dict] | None = None,
    ) -> dict:
        """
        NATRIX approves proposed mandates and dispatches to NCC.

        This is the human-in-the-loop gate. Nothing reaches NCC without
        NATRIX explicitly calling this after reviewing council output.

        Args:
            pump_id: The pump prompt ID to approve
            approved_mandate_ids: Specific mandate IDs to approve (None = approve all)
            modifications: Optional dict of mandate_id → field overrides
                           e.g. {"abc123": {"priority": 3, "objective": "revised text"}}

        Returns:
            Dict with dispatch results
        """
        async with self._pending_dispatches_lock:
            pending = self._pending_dispatches.get(pump_id)
        if not pending:
            return {"error": f"No pending dispatch found for pump {pump_id}"}

        mandates_to_dispatch = []
        blocked_by_policy: list[str] = []

        async with self._mandates_lock:
            for m in pending["mandates"]:
                if "error" in m:
                    continue

                mandate_id = m.get("mandate_id", "")

                # If specific IDs given, skip ones not approved
                if approved_mandate_ids and mandate_id not in approved_mandate_ids:
                    log.info(f"[approve] Mandate {mandate_id} not in approved list, skipping")
                    continue

                # Apply modifications if any
                mandate = self.mandates.get(mandate_id)
                if mandate:
                    if modifications and mandate_id in modifications:
                        mods = modifications[mandate_id]
                        if "priority" in mods:
                            mandate.priority = mods["priority"]
                        if "objective" in mods:
                            mandate.objective = mods["objective"]
                        if "title" in mods:
                            mandate.title = mods["title"]
                        if "success_criteria" in mods:
                            mandate.success_criteria = mods["success_criteria"]
                        log.info(f"[approve] Applied modifications to mandate {mandate_id}")

                    # Governance gate — ask the policy kernel before promoting to ACTIVE.
                    if self.policy_kernel is not None:
                        try:
                            allowed = await self._policy_allows_dispatch(mandate)
                        except Exception as exc:
                            log.warning(
                                f"[approve] Policy kernel check raised for {mandate_id}: {exc}"
                            )
                            allowed = True  # Fail-open on kernel errors
                        if not allowed:
                            log.warning(
                                f"[approve] PolicyKernel BLOCKED dispatch for mandate {mandate_id}"
                            )
                            try:
                                mandate.transition_to(
                                    MandateStatus.CANCELLED,
                                    reason="Blocked by policy kernel",
                                )
                            except ValueError:
                                mandate.updated_at = datetime.now(timezone.utc)
                            blocked_by_policy.append(mandate_id)
                            continue

                    # Promote from PENDING_APPROVAL → ACTIVE
                    try:
                        mandate.transition_to(
                            MandateStatus.ACTIVE,
                            reason=f"NATRIX approved pump {pump_id}",
                        )
                    except ValueError as e:
                        log.warning(
                            f"[approve] Invalid mandate transition for {mandate_id}: {e}"
                        )
                        mandate.updated_at = datetime.now(timezone.utc)

                    mandates_to_dispatch.append({
                        "mandate_id": mandate.mandate_id,
                        "pillar": mandate.pillar.value,
                        "title": mandate.title,
                        "priority": mandate.priority,
                    })

            await self._persist_mandates_unlocked()

        if not mandates_to_dispatch:
            return {
                "status": "no_mandates",
                "pump_id": pump_id,
                "blocked_by_policy": blocked_by_policy,
            }

        # Emergency-stop gate — refuse dispatch if engaged
        if await self._emergency_stop_engaged():
            log.warning(
                f"[approve] Emergency stop engaged — refusing dispatch for pump {pump_id}"
            )
            async with self._mandates_lock:
                for entry in mandates_to_dispatch:
                    blocked = self.mandates.get(entry["mandate_id"])
                    if blocked:
                        try:
                            blocked.transition_to(
                                MandateStatus.CANCELLED,
                                reason="Emergency stop engaged",
                            )
                        except ValueError:
                            blocked.updated_at = datetime.now(timezone.utc)
                await self._persist_mandates_unlocked()
            return {
                "status": "emergency_stop_active",
                "pump_id": pump_id,
                "mandates_blocked": [m["mandate_id"] for m in mandates_to_dispatch],
            }

        # NOW dispatch to NCC — only after NATRIX approval and policy clearance
        dispatch_result = await self._dispatch_to_ncc(mandates_to_dispatch)

        # Clean up pending
        async with self._pending_dispatches_lock:
            self._pending_dispatches.pop(pump_id, None)
            await self._persist_pending_dispatches_unlocked()

        await self._log_event(
            "strike_approved_dispatched",
            f"NATRIX approved {len(mandates_to_dispatch)} mandates from pump {pump_id}",
            {"dispatched": [m["mandate_id"] for m in mandates_to_dispatch]},
        )

        return {
            "status": "approved_and_dispatched",
            "pump_id": pump_id,
            "mandates_dispatched": len(mandates_to_dispatch),
            "dispatch": dispatch_result,
        }

    async def reject_pump(self, pump_id: str, reason: str = "") -> dict:
        """
        NATRIX rejects proposed mandates — nothing dispatched to NCC.

        Args:
            pump_id: The pump prompt ID to reject
            reason: Optional rejection reason

        Returns:
            Status dict
        """
        async with self._pending_dispatches_lock:
            pending = self._pending_dispatches.get(pump_id)
        if not pending:
            return {"error": f"No pending dispatch found for pump {pump_id}"}

        # Mark all pending mandates as CANCELLED
        async with self._mandates_lock:
            for m in pending["mandates"]:
                mandate_id = m.get("mandate_id", "")
                mandate = self.mandates.get(mandate_id)
                if mandate:
                    try:
                        mandate.transition_to(
                            MandateStatus.CANCELLED,
                            reason=f"NATRIX rejected pump {pump_id}: {reason}",
                        )
                    except ValueError as e:
                        log.warning(
                            f"[reject] Invalid mandate transition for {mandate_id}: {e}"
                        )
                        mandate.updated_at = datetime.now(timezone.utc)

            await self._persist_mandates_unlocked()
        async with self._pending_dispatches_lock:
            self._pending_dispatches.pop(pump_id, None)
            await self._persist_pending_dispatches_unlocked()

        await self._log_event(
            "strike_rejected",
            f"NATRIX rejected mandates from pump {pump_id}: {reason}",
            {"pump_id": pump_id, "reason": reason},
        )

        return {
            "status": "rejected",
            "pump_id": pump_id,
            "reason": reason,
        }

    # -------------------------------------------------------------------
    # MWP Stage Output Handoffs (Jake Van Clief protocol)
    # -------------------------------------------------------------------

    async def _mwp_write_stage(self, stage: str, filename: str, data: dict | str) -> None:
        """
        Write an artifact to a MWP stage output directory.

        Stages follow the Jake Van Clief 5-stage pipeline:
          01-intake  → raw pump prompt JSON
          02-analysis → council debate prompt + context
          03-synthesis → full council transcript + synthesis + consensus score
          04-mandate-draft → extracted mandate YAML/JSON
          05-review → final approval package

        Args:
            stage: Stage directory name (e.g., "01-intake")
            filename: Output filename
            data: Dict (→ JSON) or string (→ text) to write
        """
        output_dir = self.mwp_base / stage / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        filepath = output_dir / filename
        content = json.dumps(data, default=str, indent=2) if isinstance(data, dict) else str(data)

        async with aiofiles.open(filepath, "w") as f:
            await f.write(content)

        log.info(f"[mwp] Stage {stage} → {filepath}")

    async def _mwp_intake(self, prompt: PumpPrompt) -> None:
        """Stage 01 — Write raw pump prompt to intake output."""
        await self._mwp_write_stage("01-intake", f"pump-{prompt.prompt_id}.json", {
            "pump_id": prompt.prompt_id,
            "intent": prompt.intent,
            "source": prompt.source,
            "urgency": prompt.urgency,
            "context": prompt.context or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _mwp_analysis(self, prompt: PumpPrompt, council_prompt: str) -> None:
        """Stage 02 — Write analysis artifacts (council prompt + context)."""
        await self._mwp_write_stage("02-analysis", f"analysis-{prompt.prompt_id}.json", {
            "pump_id": prompt.prompt_id,
            "council_prompt": council_prompt,
            "intent": prompt.intent,
            "urgency": prompt.urgency,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _mwp_synthesis(self, session: CouncilSession) -> None:
        """Stage 03 — Write council transcript + synthesis + consensus score."""
        rounds_data = []
        for rnd in session.rounds:
            rounds_data.append({
                "round_number": rnd.round_number,
                "round_type": rnd.round_type,
                "responses": rnd.responses,
                "scores": rnd.scores,
            })

        await self._mwp_write_stage("03-synthesis", f"synthesis-{session.session_id}.json", {
            "session_id": session.session_id,
            "topic": session.topic,
            "protocol": session.protocol,
            "role_assignments": session.role_assignments,
            "rounds": rounds_data,
            "synthesis": session.synthesis,
            "consensus": session.consensus,
            "consensus_score": {
                "agreement_pct": session.consensus_score.agreement_pct,
                "convergence_delta": session.consensus_score.convergence_delta,
                "confidence_weighted": session.consensus_score.confidence_weighted,
                "unanimous": session.consensus_score.unanimous,
                "threshold_met": session.consensus_score.threshold_met,
                "dissent_strength": session.consensus_score.dissent_strength,
            } if session.consensus_score else None,
            "recommendations": session.recommendations,
            "dissents": session.dissents,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        })

    async def _mwp_mandate_draft(self, mandates_data: list[dict], pump_id: str) -> None:
        """Stage 04 — Write extracted mandate drafts."""
        await self._mwp_write_stage("04-mandate-draft", f"mandates-{pump_id}.json", {
            "pump_id": pump_id,
            "mandate_count": len(mandates_data),
            "mandates": [
                {
                    "pillar": m["pillar"].value if hasattr(m["pillar"], "value") else str(m["pillar"]),
                    "title": m["title"],
                    "objective": m["objective"],
                    "priority": m["priority"],
                    "success_criteria": m.get("success_criteria", []),
                }
                for m in mandates_data
            ],
            "drafted_at": datetime.now(timezone.utc).isoformat(),
        })

    async def _mwp_review(self, prompt: PumpPrompt, session: CouncilSession, mandates: list[dict]) -> None:
        """Stage 05 — Write final approval/review package."""
        await self._mwp_write_stage("05-review", f"review-{prompt.prompt_id}.json", {
            "pump_id": prompt.prompt_id,
            "intent": prompt.intent,
            "urgency": prompt.urgency,
            "council_session_id": session.session_id,
            "consensus_met": session.consensus_score.threshold_met if session.consensus_score else False,
            "consensus_pct": session.consensus_score.agreement_pct if session.consensus_score else 0,
            "mandates_generated": len(mandates),
            "mandates": mandates,
            "dissents": session.dissents,
            "review_status": "auto_approved" if (session.consensus_score and session.consensus_score.threshold_met) else "needs_natrix_review",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

    def _build_council_prompt(self, prompt: PumpPrompt) -> str:
        """Build a council debate prompt from pump prompt context."""
        context_str = ""
        if prompt.context:
            for k, v in prompt.context.items():
                context_str += f"\n- {k}: {v}"

        return (
            f"NATRIX has issued a directive via strike point.\n\n"
            f"INTENT: {prompt.intent}\n"
            f"URGENCY: {prompt.urgency}\n"
            f"SOURCE: {prompt.source}\n"
            f"CONTEXT:{context_str if context_str else ' (none provided)'}\n\n"
            f"As the council, debate and determine:\n"
            f"1. Which pillar(s) should receive mandates (NCC, BRS, AAC)?\n"
            f"2. What is the strategic objective for each mandate?\n"
            f"3. What are the success criteria?\n"
            f"4. Priority level (1-10)?\n"
            f"5. Any risks or blockers to flag?\n\n"
            f"Format your recommendation clearly with PILLAR, TITLE, OBJECTIVE, "
            f"PRIORITY, and SUCCESS_CRITERIA for each proposed mandate."
        )

    def _extract_mandates_from_council(
        self, session: CouncilSession, prompt: PumpPrompt
    ) -> list[dict]:
        """Extract structured mandates from council consensus/recommendations."""
        mandates = []
        text = (session.consensus or "") + "\n" + "\n".join(session.recommendations)
        text_lower = text.lower()

        # Try to parse structured mandate blocks from council output

        # Look for PILLAR: mentions
        pillar_map = {
            "ncc": PillarType.NCC,
            "brs": PillarType.BRS,
            "aac": PillarType.AAC,
        }

        # Pattern: PILLAR: NCC ... TITLE: ... OBJECTIVE: ... PRIORITY: N
        blocks = re.split(r'(?:^|\n)(?=(?:PILLAR|Pillar|pillar)\s*:)', text)
        for block in blocks:
            if not block.strip():
                continue
            pillar_match = re.search(r'(?:PILLAR|Pillar|pillar)\s*:\s*(\w+)', block)
            title_match = re.search(r'(?:TITLE|Title|title)\s*:\s*(.+?)(?:\n|$)', block)
            obj_match = re.search(r'(?:OBJECTIVE|Objective|objective)\s*:\s*(.+?)(?:\n|$)', block)
            pri_match = re.search(r'(?:PRIORITY|Priority|priority)\s*:\s*(\d+)', block)
            criteria_matches = re.findall(r'(?:SUCCESS_CRITERIA|criteria)\s*:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)

            if pillar_match:
                pillar_key = pillar_match.group(1).lower().strip()
                if pillar_key in pillar_map:
                    mandates.append({
                        "pillar": pillar_map[pillar_key],
                        "title": title_match.group(1).strip() if title_match else f"Mandate from pump {prompt.prompt_id}",
                        "objective": obj_match.group(1).strip() if obj_match else prompt.intent,
                        "priority": min(10, max(1, int(pri_match.group(1)))) if pri_match else (8 if prompt.urgency == "critical" else 5),
                        "success_criteria": [c.strip() for c in criteria_matches] if criteria_matches else [],
                    })

        # Fallback: if no structured mandates found, create one from intent
        if not mandates:
            # Determine target pillar from intent keywords
            target = PillarType.NCC  # Default to NCC
            if any(w in text_lower for w in ["revenue", "ship", "product", "earn", "freelance"]):
                target = PillarType.BRS
            elif any(w in text_lower for w in ["invest", "capital", "trade", "war room", "portfolio"]):
                target = PillarType.AAC

            mandates.append({
                "pillar": target,
                "title": f"Directive: {prompt.intent[:80]}",
                "objective": prompt.intent,
                "priority": 8 if prompt.urgency == "critical" else 6 if prompt.urgency == "high" else 5,
                "success_criteria": session.recommendations[:5] if session.recommendations else [],
            })

        return mandates

    async def _dispatch_to_ncc(self, mandates: list[dict]) -> dict:
        """Dispatch mandates to NCC for execution."""
        ncc_host = os.getenv("NCC_HOST", "http://localhost")
        ncc_port = int(os.getenv("NCC_PORT", "8787"))
        url = f"{ncc_host}:{ncc_port}/mandate/intake"

        dispatched = []
        failed = []

        try:
            client = await _get_brain_http_client()
            for m in mandates:
                if "error" in m:
                    continue
                mandate_id = m.get("mandate_id", "")
                try:
                    # Build NCC-compatible MandateRequest payload
                    pillar_val = m.get("pillar", "ncc")
                    if hasattr(pillar_val, "value"):
                        pillar_val = pillar_val.value.upper()
                    else:
                        pillar_val = str(pillar_val).upper()
                    # Map pillar to NCC TargetPillar enum (BRS or AAC)
                    target_list = []
                    if pillar_val in ("BRS", "AAC"):
                        target_list = [pillar_val]
                    else:
                        target_list = ["BRS"]  # Default: NCC dispatches to BRS

                    # Map priority int (1-10) to NCC PriorityLevel
                    pri = m.get("priority", 5)
                    if pri >= 8:
                        priority_level = "P0"
                    elif pri >= 6:
                        priority_level = "P1"
                    elif pri >= 4:
                        priority_level = "P2"
                    else:
                        priority_level = "P3"

                    # Only set a deadline if the mandate doesn't already have one
                    mandate_obj = self.mandates.get(mandate_id)
                    existing_deadline = getattr(mandate_obj, "deadline", None) if mandate_obj else None
                    deadline_val = (
                        existing_deadline.isoformat()
                        if existing_deadline is not None
                        else (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                    )
                    resp = await client.post(url, json={
                        "mandate_id": mandate_id,
                        "title": m.get("title", "Untitled mandate"),
                        "description": m.get("objective", m.get("title", "Mandate from NCL")),
                        "deadline": deadline_val,
                        "priority": priority_level,
                        "target_pillar": target_list,
                        "success_criteria": m.get("success_criteria", ["Complete as directed"]),
                        "tags": ["ncl-generated", "strike-point"],
                    }, timeout=15.0)
                    if resp.status_code < 400:
                        dispatched.append(mandate_id or m.get("title"))
                    else:
                        err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        log.error(f"[dispatch] NCC rejected mandate {mandate_id}: {err_msg}")
                        failed.append({"mandate": m.get("title"), "mandate_id": mandate_id, "error": err_msg})
                        # Mark mandate as failed
                        await self._mark_dispatch_failed(mandate_id, err_msg)
                except Exception as e:
                    log.error(f"[dispatch] Failed to dispatch mandate {mandate_id}: {e}")
                    failed.append({"mandate": m.get("title"), "mandate_id": mandate_id, "error": str(e)})
                    # Mark mandate as failed
                    await self._mark_dispatch_failed(mandate_id, str(e))
        except Exception as e:
            log.error(f"[dispatch] NCC unreachable at {url}: {e}")
            # Mark all mandates in this batch as failed
            for m in mandates:
                mid = m.get("mandate_id", "")
                if mid and "error" not in m:
                    await self._mark_dispatch_failed(mid, f"NCC unreachable: {e}")
            return {"status": "ncc_unreachable", "error": str(e)}

        return {
            "status": "dispatched",
            "dispatched": dispatched,
            "failed": failed,
        }

    async def _mark_dispatch_failed(self, mandate_id: str, reason: str) -> None:
        """Mark a mandate as FAILED after dispatch error."""
        if not mandate_id:
            return
        async with self._mandates_lock:
            mandate = self.mandates.get(mandate_id)
            if mandate and mandate.status == MandateStatus.ACTIVE:
                try:
                    mandate.transition_to(
                        MandateStatus.FAILED,
                        reason=f"Dispatch failed: {reason}",
                    )
                except (ValueError, AttributeError):
                    # If FAILED status doesn't exist or transition not allowed,
                    # mark updated_at so it's visible in state
                    mandate.updated_at = datetime.now(timezone.utc)
                    log.warning(f"[dispatch] Could not transition {mandate_id} to FAILED")
                await self._persist_mandates_unlocked()

    async def spawn_council_session(
        self, topic: str, prompt: str, members: Optional[list[str]] = None
    ) -> CouncilSession:
        """
        Spawn a new council debate session.

        Args:
            topic: Debate topic
            prompt: Chair's prompt
            members: Council member names (strings converted to CouncilMember enums)

        Returns:
            CouncilSession
        """
        # Convert string member names to CouncilMember enums
        member_enums: Optional[list[CouncilMember]] = None
        if members:
            member_enums = []
            for m in members:
                try:
                    member_enums.append(CouncilMember(m.lower()))
                except ValueError:
                    log.warning(f"Unknown council member '{m}', skipping")

        session = await self.council_engine.spawn_session(topic, prompt, member_enums)
        async with self._council_sessions_lock:
            # Evict oldest sessions when at capacity
            if len(self.council_sessions) >= self._COUNCIL_SESSIONS_MAX:
                self._evict_oldest_council_sessions()
            self.council_sessions[session.session_id] = session

        await self._log_event(
            "council_spawned",
            f"Council session on {topic}",
            {"session_id": session.session_id},
        )

        # Run debate
        session = await self.council_engine.run_debate(session)
        await self._log_event(
            "council_completed",
            f"Council session {session.session_id} completed",
            {
                "topic": topic,
                "consensus": session.consensus,
                "recommendations": session.recommendations,
            },
        )

        # Store insights in memory
        await self.memory_store.create_unit(
            content=f"Council consensus: {session.consensus}",
            source=f"council:{session.session_id}",
            importance=70.0,
            tags=["council", "consensus", topic.lower()],
        )

        return session

    async def create_mandate(
        self,
        pillar: PillarType,
        priority: int,
        title: str,
        objective: str,
        success_criteria: list[str],
        deadline: Optional[datetime] = None,
        source_pump_id: Optional[str] = None,
        status: MandateStatus = MandateStatus.ACTIVE,
    ) -> Mandate:
        """
        Create a new mandate for a pillar.

        Args:
            pillar: Target pillar (NCC, BRS, AAC)
            priority: Priority 1-10
            title: Mandate title
            objective: Strategic objective
            success_criteria: Success criteria
            deadline: Target deadline
            source_pump_id: Source pump prompt ID
            status: Initial status (PENDING_APPROVAL for auto-flow, ACTIVE for direct)

        Returns:
            Created Mandate
        """
        mandate = Mandate(
            mandate_id=str(uuid.uuid4()),
            pillar=pillar,
            priority=priority,
            title=title,
            objective=objective,
            success_criteria=success_criteria,
            deadline=deadline,
            status=status,
            source_pump_id=source_pump_id,
        )

        # Governance gate — direct programmatic mandate creation also goes
        # through the policy kernel (graceful degradation when unset).
        if status == MandateStatus.ACTIVE and self.policy_kernel is not None:
            try:
                allowed = await self._policy_allows_dispatch(mandate)
            except Exception as exc:
                log.warning(f"[create_mandate] Policy kernel check raised: {exc}")
                allowed = True
            if not allowed:
                log.warning(
                    f"[create_mandate] PolicyKernel BLOCKED mandate {mandate.mandate_id}; "
                    "marking CANCELLED instead of ACTIVE"
                )
                try:
                    mandate.transition_to(
                        MandateStatus.CANCELLED,
                        reason="PolicyKernel blocked dispatch at creation",
                    )
                except ValueError:
                    # Direct fallback if transition not permitted from current state
                    mandate.status = MandateStatus.CANCELLED

        async with self._mandates_lock:
            self.mandates[mandate.mandate_id] = mandate
            await self._persist_mandates_unlocked()

        # Create issue in Paperclip
        try:
            issue_id = await self.paperclip.create_mandate_as_issue(
                mandate_id=mandate.mandate_id,
                pillar=mandate.pillar.value,
                title=mandate.title,
                objective=mandate.objective,
                priority="high" if mandate.priority >= 7 else "medium" if mandate.priority >= 4 else "low",
                assigned_agent_id=None,
                success_criteria=mandate.success_criteria,
                deadline=mandate.deadline.isoformat() if mandate.deadline else None,
            )
            await self._log_event(
                "mandate_created",
                f"Mandate {mandate.mandate_id} for {pillar.value}",
                {"mandate_id": mandate.mandate_id, "issue_id": issue_id, "priority": priority},
            )
        except Exception as e:
            await self._log_event("mandate_error", f"Failed to create Paperclip issue: {e}")

        return mandate

    async def get_mandate(self, mandate_id: str) -> Optional[Mandate]:
        """
        Get a mandate by ID.

        Args:
            mandate_id: Mandate ID

        Returns:
            Mandate or None
        """
        return self.mandates.get(mandate_id)

    async def list_mandates(
        self, pillar: Optional[PillarType] = None, status: Optional[MandateStatus] = None
    ) -> list[Mandate]:
        """
        List mandates with optional filters.

        Args:
            pillar: Filter by pillar
            status: Filter by status

        Returns:
            List of Mandates
        """
        result = list(self.mandates.values())

        if pillar:
            result = [m for m in result if m.pillar == pillar]
        if status:
            result = [m for m in result if m.status == status]

        return result

    # -------------------------------------------------------------------
    # Governance Integration — Policy Kernel + Emergency Stop
    # -------------------------------------------------------------------

    async def _policy_allows_dispatch(self, mandate: Mandate) -> bool:
        """
        Check if the PolicyKernel allows dispatching this mandate.

        Uses the governance Action model to evaluate Execute-tier dispatch.
        Returns True if allowed, False if blocked.
        Gracefully returns True if policy_kernel is None (fail-open).
        """
        if self.policy_kernel is None:
            return True

        try:
            from ..governance.models import Action, ActionTier
            action = Action(
                name=f"dispatch_mandate:{mandate.mandate_id}",
                tier=ActionTier.EXECUTE,
                source_agent="NCL:brain",
                target=mandate.pillar.value if hasattr(mandate.pillar, "value") else str(mandate.pillar),
                description=f"Dispatch mandate: {mandate.title}",
                payload={
                    "mandate_id": mandate.mandate_id,
                    "pump_id": mandate.source_pump_id or "",
                    "title": mandate.title,
                    "priority": mandate.priority,
                    "objective": mandate.objective[:200],
                },
            )
            allowed, reason = self.policy_kernel.execute_if_allowed(action)
            if not allowed:
                log.warning(f"[governance] PolicyKernel blocked mandate {mandate.mandate_id}: {reason}")
            return allowed
        except Exception as e:
            log.warning(f"[governance] Policy check error: {e}")
            return True  # Fail-open on errors

    async def _emergency_stop_engaged(self) -> bool:
        """
        Check if the emergency stop kill switch is active.

        Returns True if emergency stop is active (all dispatches should halt).
        Returns False if emergency stop is not initialized or not active.
        """
        if self.emergency_stop is None:
            return False

        try:
            return self.emergency_stop.is_active
        except Exception as e:
            log.warning(f"[governance] Emergency stop check error: {e}")
            return False  # Fail-open on errors

    async def complete_mandate(self, mandate_id: str, notes: Optional[str] = None) -> None:
        """
        Mark a mandate as completed.

        Args:
            mandate_id: Mandate ID
            notes: Completion notes
        """
        mandate = self.mandates.get(mandate_id)
        if not mandate:
            return

        async with self._mandates_lock:
            try:
                mandate.transition_to(
                    MandateStatus.COMPLETED,
                    reason=notes or "Mandate completed",
                )
            except ValueError as e:
                log.warning(
                    f"[complete] Invalid mandate transition for {mandate_id}: {e}"
                )
                mandate.updated_at = datetime.now(timezone.utc)
            await self._persist_mandates_unlocked()

        await self._log_event(
            "mandate_completed",
            f"Mandate {mandate_id} completed",
            {"mandate_id": mandate_id, "notes": notes},
        )

    async def receive_feedback(self, feedback: FeedbackReport) -> str:
        """
        Receive feedback from downstream pillar.

        Args:
            feedback: FeedbackReport from pillar

        Returns:
            Report ID
        """
        await self._log_event(
            "feedback_received",
            f"Feedback from {feedback.origin.value}",
            {
                "report_id": feedback.report_id,
                "lessons": feedback.lessons,
                "recommendations": feedback.recommendations,
            },
        )

        # Store in memory
        await self.memory_store.create_unit(
            content=f"Feedback from {feedback.origin.value}: {feedback.content}",
            source=f"feedback:{feedback.origin.value}",
            importance=65.0,
            tags=["feedback", feedback.origin.value, "lessons"],
        )

        return feedback.report_id

    async def query_memory(
        self,
        tags: Optional[list[str]] = None,
        importance_threshold: float = 0.0,
        days_back: Optional[int] = None,
    ) -> dict:
        """
        Query memory with filters.

        Args:
            tags: Search tags (AND logic)
            importance_threshold: Minimum importance
            days_back: Days in past to search

        Returns:
            Dict with results
        """
        units = await self.memory_store.search_units(
            tags=tags,
            importance_threshold=importance_threshold,
            days_back=days_back,
        )

        return {
            "count": len(units),
            "units": [
                {
                    "id": u.unit_id,
                    "content": u.content,
                    "source": u.source,
                    "importance": u.importance,
                    "tags": u.tags,
                }
                for u in units
            ],
        }

    async def run_awarebot_scan(self, queries: list[str]) -> dict:
        """
        Run Awarebot intelligence scan.

        Args:
            queries: List of search queries

        Returns:
            Dict with scan results
        """
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": {"x": [], "youtube": [], "reddit": []},
        }

        for query in queries:
            # X scan
            x_signals = await self.scanner.scan_x(query, max_results=5)
            results["sources"]["x"].extend(
                [
                    {
                        "signal_id": s.signal_id,
                        "content": s.content[:100],
                        "importance": s.importance_score,
                        "url": s.url,
                    }
                    for s in x_signals
                ]
            )

            # YouTube scan
            yt_signals = await self.scanner.scan_youtube(query, max_results=3)
            results["sources"]["youtube"].extend(
                [
                    {
                        "signal_id": s.signal_id,
                        "content": s.content[:100],
                        "importance": s.importance_score,
                        "url": s.url,
                    }
                    for s in yt_signals
                ]
            )

            # Reddit scan
            try:
                reddit_signals = await self.scanner.scan_reddit(query, max_results=5)
                results["sources"]["reddit"].extend(
                    [
                        {
                            "signal_id": s.signal_id,
                            "content": s.content[:100],
                            "importance": s.importance_score,
                            "url": getattr(s, "url", ""),
                        }
                        for s in reddit_signals
                    ]
                )
            except Exception as e:
                log.warning(f"[awarebot] Reddit scan failed for '{query}': {e}")

        await self._log_event("awarebot_scan", f"Scanned {len(queries)} queries", results)
        return results

    async def run_prediction(self, topic: str) -> dict:
        """
        Run Future Predictor ensemble forecast.

        Args:
            topic: Prediction topic

        Returns:
            Dict with prediction results
        """
        # Gather signals from memory
        memory_results = await self.query_memory(
            tags=[topic.lower()],
            importance_threshold=50.0,
            days_back=7,
        )

        # Build real InsightSignal objects from memory results
        signals = []
        for unit in memory_results.get("units", []):
            content = unit.get("content", "")
            importance = float(unit.get("importance", 50.0))
            if not content:
                continue
            signals.append(
                InsightSignal(
                    signal_id=str(uuid.uuid4()),
                    source_platform="memory",
                    content=content[:500],
                    importance_score=importance,
                    relevance=min(1.0, importance / 100.0),
                    novelty=0.5,
                    actionability=0.5,
                    source_authority=0.7,
                    time_sensitivity=0.5,
                    timestamp=datetime.now(timezone.utc),
                    tags=unit.get("tags", [topic.lower()]),
                )
            )

        if not signals:
            return {
                "prediction_id": str(uuid.uuid4()),
                "topic": topic,
                "consensus": "no data — no memory signals found for this topic",
                "confidence": 0.0,
                "convergence": [],
                "warnings": [f"No memory units found for topic '{topic}' in the past 7 days"],
            }

        prediction_output = await self.predictor.predict(signals, topic)

        await self._log_event(
            "prediction_generated",
            f"Prediction for {topic}",
            {
                "confidence": prediction_output.confidence,
                "convergence": prediction_output.convergence_signals,
            },
        )

        return {
            "prediction_id": prediction_output.prediction_id,
            "topic": prediction_output.topic,
            "consensus": prediction_output.consensus_prediction,
            "confidence": prediction_output.confidence,
            "convergence": prediction_output.convergence_signals,
            "warnings": prediction_output.warnings,
        }

    async def dispatch_research(self, query: str, depth: str = "standard", priority: int = 5) -> dict:
        """
        Dispatch a research task to UNI Research Cortex.

        Bridges brain → cortex so pump prompts and councils can trigger
        deep research without going through routes.py.

        Args:
            query: Research question
            depth: Research depth (quick, standard, deep, exhaustive)
            priority: Priority 1-10

        Returns:
            Research task status dict
        """
        if self.research_cortex is None:
            return {"error": "Research Cortex not initialized"}

        try:
            result = await self.research_cortex.research(
                query=query, depth=depth, priority=priority
            )
            # Store research completion in memory
            await self.memory_store.create_unit(
                content=f"Research completed: {query}",
                source="uni:cortex",
                importance=60.0,
                tags=["research", "uni", depth],
            )
            await self._log_event(
                "research_dispatched",
                f"UNI research: {query[:80]}",
                {"depth": depth, "priority": priority},
            )
            return {"status": "completed", "query": query, "result": result}
        except Exception as e:
            log.error(f"Research dispatch failed: {e}")
            return {"error": str(e), "query": query}

    async def submit_swarm_task(
        self,
        title: str,
        objective: str,
        priority: int = 5,
        budget_cents: int = 5000,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """
        Submit a task to the agent swarm for autonomous multi-LLM execution.

        Args:
            title: Short human-readable task title.
            objective: Full description of what to accomplish.
            priority: 1 (lowest) to 10 (highest).
            budget_cents: Maximum spend allowed for this task.
            tags: Optional classification tags.

        Returns:
            Dict with task_id, title, status, and priority.
        """
        task = await self.swarm.submit_task(
            title=title,
            objective=objective,
            priority=priority,
            budget_cents=budget_cents,
            tags=tags or [],
        )

        await self._log_event(
            "swarm_task_submitted",
            f"Swarm task submitted: {title}",
            {
                "task_id": task.task_id,
                "priority": priority,
                "budget_cents": budget_cents,
                "tags": tags or [],
            },
        )

        return {
            "task_id": task.task_id,
            "title": task.title,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "priority": task.priority,
            "budget_cents": task.budget_cents,
        }

    async def health_check(self) -> dict:
        """
        Health check endpoint — enriched for MATRIX MONITOR.

        Returns:
            Health status dict with all data MATRIX MONITOR needs
        """
        active_mandates = [m for m in self.mandates.values() if m.status in (MandateStatus.ACTIVE, MandateStatus.IN_PROGRESS)]
        pending_approval = [m for m in self.mandates.values() if m.status == MandateStatus.PENDING_APPROVAL]
        memory_stats = await self.memory_store.get_stats() if hasattr(self.memory_store, "get_stats") else {}

        # Degraded-state thresholds. The May 2026 corruption hit 22,388
        # mandates before discovery; flagging at 1000 / 50 catches similar
        # leaks within a few hours instead of months.
        warnings: list[str] = []
        total = len(self.mandates)
        if total > 1000:
            warnings.append(f"mandates_total={total} exceeds 1000 \u2014 possible state leak")
        if len(pending_approval) > 50:
            warnings.append(
                f"pending_approval={len(pending_approval)} exceeds 50 \u2014 approval queue blocked"
            )
        status = "degraded" if warnings else "healthy"

        # Best-effort ntfy alarm (rate-limited via internal flag so we don't spam)
        if warnings and not getattr(self, "_health_alarm_sent", False):
            self._health_alarm_sent = True
            try:
                topic = os.getenv("NTFY_TOPIC")
                ntfy_server = os.getenv("NTFY_SERVER", "https://ntfy.sh")
                if topic:
                    _client = await _get_brain_http_client()
                    await _client.post(
                        f"{ntfy_server}/{topic}",
                        content="; ".join(warnings).encode(),
                        headers={
                            "Title": "NCL Brain DEGRADED",
                            "Priority": "high",
                            "Tags": "warning,ncl",
                        },
                        timeout=5.0,
                    )
            except Exception as exc:
                log.warning(f"ntfy degraded-alarm send failed: {exc!r}")
        elif not warnings and getattr(self, "_health_alarm_sent", False):
            # Auto-reset so the next degradation re-alarms
            self._health_alarm_sent = False

        return {
            "status": status,
            "service": "ncl-brain",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_pct": 100.0,
            # MATRIX MONITOR fields
            "active_mandates": len(active_mandates),
            "mandates_total": total,
            "pending_approval": len(pending_approval),
            "council_sessions": len(self.council_sessions),
            "memory_units": memory_stats.get("total_units", 0),
            "key_metric": len(active_mandates),
            "key_metric_label": "active_mandates",
            "paperclip_connected": getattr(self, "_paperclip_connected", False),
            "warnings": warnings,
        }

    async def shutdown(self) -> None:
        """Shutdown brain on exit."""
        # Cancel periodic cleanup task
        if hasattr(self, "_cleanup_task") and self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        # Persist final state
        async with self._pending_dispatches_lock:
            await self._persist_pending_dispatches_unlocked()
        await self.swarm.shutdown()
        await self.council_engine.close()
        await self.scanner.close()
        await self.predictor.close()
        await self.paperclip.close()

    async def _log_event(
        self,
        event_type: str,
        description: str,
        metadata: Optional[dict] = None,
        *,
        parent_event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        pump_id: Optional[str] = None,
        mandate_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        importance: float = 50.0,
    ) -> str:
        """
        Log an event to NDJSON file and Paperclip using Event Schema v1.

        Accepts the old (type, description, metadata) signature for backwards
        compatibility, plus optional provenance keyword args for new callers.

        Args:
            event_type: Type of event (string or EventType)
            description: Event description
            metadata: Additional payload data
            parent_event_id: Event that caused this one
            correlation_id: Shared chain ID (pump→mandate→execution)
            pump_id: Originating pump prompt ID
            mandate_id: Related mandate ID
            session_id: Council/debate session ID
            tags: Searchable tags
            importance: Importance score 0-100

        Returns:
            event_id of the created event
        """
        ncl_event = NCLEvent.quick(
            event_type=event_type,
            description=description,
            source_agent="ncl-brain",
            payload=metadata or {},
            parent_event_id=parent_event_id,
            correlation_id=correlation_id,
            pump_id=pump_id,
            mandate_id=mandate_id,
            session_id=session_id,
            tags=tags,
            importance=importance,
        )

        # Rotate events file if it has grown too large (synchronous stat check)
        self._rotate_events_file_if_needed()

        # Write v1 schema to NDJSON (backwards-compatible dict format)
        async with aiofiles.open(self.events_file, "a") as f:
            await f.write(ncl_event.to_ndjson() + "\n")

        # Log to Paperclip (best-effort; do not raise into caller)
        try:
            await self.paperclip.log_activity(
                activity_type=event_type,
                description=description,
                agent_name="NCL",
                metadata=metadata,
            )
        except Exception as exc:
            # Avoid log spam when Paperclip is offline; rate-limited via _paperclip_connected
            if getattr(self, "_paperclip_connected", False):
                log.warning(f"[paperclip] log_activity failed: {exc}")
                self._paperclip_connected = False

        return ncl_event.event_id

    def _rotate_events_file_if_needed(self) -> None:
        """
        Synchronous rotation for events.ndjson.

        Shifts existing backups (.1 -> .2 up to _events_rotate_backups),
        then renames the current file to .1, starting a fresh log.
        Called before every event write -- the stat() check is cheap.
        """
        try:
            if (
                not self.events_file.exists()
                or self.events_file.stat().st_size < self._events_file_max_bytes
            ):
                return
            # Shift old backups upward
            for i in range(self._events_rotate_backups - 1, 0, -1):
                src = self.events_file.with_suffix(f".ndjson.{i}")
                dst = self.events_file.with_suffix(f".ndjson.{i + 1}")
                if src.exists():
                    src.rename(dst)
            # Rotate current -> .1
            rotated = self.events_file.with_suffix(".ndjson.1")
            self.events_file.rename(rotated)
            log.info(
                "Rotated events.ndjson -> %s (exceeded %d MB)",
                rotated.name,
                self._events_file_max_bytes // (1024 * 1024),
            )
        except OSError as exc:
            log.warning("events.ndjson rotation failed: %s", exc)

    def _evict_oldest_council_sessions(self) -> None:
        """
        Evict the oldest 10% of council sessions when the dict hits capacity.

        Caller MUST hold _council_sessions_lock.
        Sessions are sorted by completed_at (oldest first); sessions without
        a completion timestamp are treated as oldest.
        """
        evict_count = max(1, self._COUNCIL_SESSIONS_MAX // 10)
        sorted_ids = sorted(
            self.council_sessions.keys(),
            key=lambda sid: (
                self.council_sessions[sid].completed_at or datetime.min.replace(tzinfo=timezone.utc)
            ),
        )
        for sid in sorted_ids[:evict_count]:
            del self.council_sessions[sid]
        log.info(f"[council_sessions] Evicted {evict_count} oldest sessions (limit={self._COUNCIL_SESSIONS_MAX})")

    async def cleanup_council_sessions(self, max_age_hours: int = 1) -> int:
        """
        Remove council sessions older than max_age_hours.

        Async-safe. Returns the number of sessions removed.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
        removed = 0
        async with self._council_sessions_lock:
            stale = [
                sid for sid, s in self.council_sessions.items()
                if s.completed_at and s.completed_at.timestamp() < cutoff
            ]
            for sid in stale:
                del self.council_sessions[sid]
                removed += 1
        if removed:
            log.info(f"[council_sessions] Cleaned up {removed} sessions older than {max_age_hours}h")
        return removed

    async def _load_state(self) -> None:
        """Load mandates from disk on startup."""
        if self.mandates_file.exists():
            async with aiofiles.open(self.mandates_file) as f:
                content = await f.read()
                if content:
                    try:
                        mandates_data = json.loads(content)
                    except (json.JSONDecodeError, ValueError) as exc:
                        log.error(f"[load_state] Corrupt mandates file — skipping load: {exc}")
                        mandates_data = []
                    for mandate_dict in mandates_data:
                        try:
                            mandate = Mandate(**mandate_dict)
                            self.mandates[mandate.mandate_id] = mandate
                        except Exception as exc:
                            log.error(f"[load_state] Skipping malformed mandate entry: {exc}")

    async def _persist_mandates(self) -> None:
        """
        Persist mandates to disk (atomic write).

        Always acquires _mandates_lock before writing. Callers that already
        hold the lock should call _persist_mandates_unlocked() directly to
        avoid a deadlock. The previous heuristic (checking .locked()) was
        not safe — asyncio.Lock.locked() returns True even when held by a
        *different* coroutine, so the heuristic could skip lock acquisition
        when it was actually needed.
        """
        async with self._mandates_lock:
            await self._persist_mandates_unlocked()

    async def _persist_mandates_unlocked(self) -> None:
        """Internal — assumes _mandates_lock is already held by caller."""
        # Snapshot to avoid concurrent-mutation iteration errors
        snapshot = [m.model_dump() for m in list(self.mandates.values())]
        tmp_path = self.mandates_file.with_suffix(self.mandates_file.suffix + ".tmp")
        payload = json.dumps(snapshot, default=str, indent=2)
        await asyncio.to_thread(self._atomic_write_json, tmp_path, self.mandates_file, payload)

    # -------------------------------------------------------------------
    # Pending Dispatches Persistence
    # -------------------------------------------------------------------

    async def _load_pending_dispatches(self) -> None:
        """Load pending dispatches from disk on startup."""
        if not self._pending_dispatches_file.exists():
            return
        try:
            async with aiofiles.open(self._pending_dispatches_file) as f:
                content = await f.read()
            if content:
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, ValueError) as exc:
                    log.error(f"[load_state] Corrupt pending_dispatches file — skipping: {exc}")
                    return
                if isinstance(data, dict):
                    for k, v in data.items():
                        self._pending_dispatches[k] = v
                    # Enforce max size
                    while len(self._pending_dispatches) > self._PENDING_DISPATCHES_MAX:
                        self._pending_dispatches.popitem(last=False)
                    log.info(f"[load_state] Loaded {len(self._pending_dispatches)} pending dispatches")
        except OSError as exc:
            log.error(f"[load_state] Could not read pending_dispatches file: {exc}")

    async def _persist_pending_dispatches_unlocked(self) -> None:
        """Persist pending dispatches to disk. Caller must hold _pending_dispatches_lock."""
        try:
            payload = json.dumps(dict(self._pending_dispatches), default=str, indent=2)
            tmp_path = self._pending_dispatches_file.with_suffix(".json.tmp")
            await asyncio.to_thread(
                self._atomic_write_json, tmp_path, self._pending_dispatches_file, payload
            )
        except Exception as exc:
            log.error(f"[persist] Failed to save pending_dispatches: {exc}")

    # -------------------------------------------------------------------
    # Periodic Council Session Cleanup
    # -------------------------------------------------------------------

    async def _periodic_council_cleanup(self) -> None:
        """Background task: clean up zombie council sessions every 15 minutes."""
        while True:
            try:
                await asyncio.sleep(900)  # 15 minutes
                await self.cleanup_council_sessions(max_age_hours=1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning(f"[cleanup] Council session cleanup error: {exc}")

    @staticmethod
    def _atomic_write_json(tmp_path: Path, target: Path, payload: str) -> None:
        with open(tmp_path, "w") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync may fail on some filesystems; don't crash persistence
                pass
        os.replace(tmp_path, target)
