"""Main NCL brain service."""

import asyncio
import json
import logging
import os
import re
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles
import httpx

from ..config import flags


# ── SQLite units-index fast path (W6-A) ───────────────────────────────────
#
# When ``NCL_UNITS_INDEX_SQLITE=true``, try the SQLite ``units_index`` table
# first (W4-14, store.py:_search_units_via_sqlite_index) so we don't have to
# full-scan the 200MB units.jsonl. Falls back to the canonical
# ``search_units`` path on flag-off or ANY failure — flag-off behavior is
# bit-identical to before this retrofit.
async def _maybe_indexed_search(memory_store, **kwargs):
    """Drop-in replacement for ``memory_store.search_units(**kwargs)``."""
    if flags.units_index_sqlite():
        try:
            unit_ids = await memory_store._search_units_via_sqlite_index(**kwargs)
            if unit_ids:
                units_by_id = await memory_store._load_units_batch(set(unit_ids))
                return [units_by_id[uid] for uid in unit_ids if uid in units_by_id]
        except Exception as e:
            logging.getLogger(__name__).debug(
                "[BRAIN] sqlite index search failed (%s) — falling back", e
            )
    return await memory_store.search_units(**kwargs)


# ---------------------------------------------------------------------------
# Config validation — fail fast on missing required env vars
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS = [
    "ANTHROPIC_API_KEY",
]

_OPTIONAL_BUT_WARNED_ENV_VARS = [
    "NCC_HOST",
    "NCC_PORT",
]


def _validate_config() -> None:
    """Validate required environment variables exist at import time.

    Loads .env file first since pydantic_settings only populates the Settings
    object, not os.environ, and the restart script doesn't source .env either.
    """
    # Load .env into os.environ if not already set (lightweight, no dependencies)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

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

# ---------------------------------------------------------------------------
# SQLite double-write hook for mandates
# ---------------------------------------------------------------------------
# OFF by default. NATRIX flips this after a 1-2 week burn-in once
# scripts/migrate_mandates_to_sqlite.py has back-filled the SQLite table.
# When True, _persist_mandates_unlocked also INSERT OR REPLACEs each
# mandate into the SQLite `mandates` table. The JSONL/JSON write remains
# the source of truth — SQLite failures NEVER block the JSON path.
SQLITE_DOUBLE_WRITE = flags.mandates_sqlite()

from ..awarebot import FuturePredictor, Scanner  # noqa: E402
from ..governance.emergency_stop import EMERGENCY_STOP_EVENT  # noqa: E402
from ..memory import MemoryStore  # noqa: E402
from ..swarm.blackboard import Blackboard  # noqa: E402
from ..swarm.llm_adapter import LLMClientAdapter  # noqa: E402
from ..swarm.orchestrator import SwarmOrchestrator  # noqa: E402
from .council import CouncilEngine  # noqa: E402
from .models import (  # noqa: E402
    CouncilMember,
    CouncilSession,
    CouncilStatus,
    FeedbackReport,
    InsightSignal,
    Mandate,
    MandateStatus,
    NCLEvent,
    PillarType,
    PumpPrompt,
)


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
        """
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Event log and state files
        self.events_file = self.data_dir / "events.ndjson"
        self.mandates_file = self.data_dir / "mandates.json"
        self.state_file = self.data_dir / "state.json"
        self._pending_dispatches_file = self.data_dir / "pending_dispatches.json"
        self._council_sessions_file = self.data_dir / "council_sessions.json"

        # Council quality metrics — counts per terminal status (complete /
        # failed / synthesizing-stuck). Exposed via /council/quality so we
        # can surface accepted vs rejected at the pipeline boundary.
        self._council_quality: dict[str, int] = {}

        # Event log rotation: rotate events.ndjson when it exceeds 100 MB
        self._events_file_max_bytes = 100 * 1024 * 1024  # 100 MB
        self._events_rotate_backups = 5

        # Paperclip adapter removed — never deployed a real backend.
        # Brain runs in degraded mode (in-memory cost tracking, no audit trail).
        # Council paperclip_client=None disables all Paperclip calls (guard checks).
        self.paperclip = None

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
            paperclip_client=None,
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
            accuracy_file=Path(data_dir).expanduser() / "predictions" / "accuracy.jsonl",
        )

        # MWP output directories for stage handoffs (Jake Van Clief protocol)
        self.mwp_base = (
            Path(data_dir).expanduser().parent / "workspaces" / "mandate-generation" / "stages"
        )

        # In-memory state (bounded collections to prevent unbounded growth)
        self.mandates: dict[str, Mandate] = {}
        self._mandates_lock = asyncio.Lock()
        # SQLite double-write — lazy-acquired SqliteStore singleton + flap
        # suppression flag so we don't spam logs if the table is unavailable.
        self._mandates_sqlite = None
        self._sqlite_warned = False
        self.council_sessions: OrderedDict[str, CouncilSession] = OrderedDict()
        self._council_sessions_lock = asyncio.Lock()  # Guards council_sessions dict
        self._COUNCIL_SESSIONS_MAX = 50  # Evict oldest completed sessions when full
        self._pending_dispatches: OrderedDict[str, dict] = (
            OrderedDict()
        )  # pump_id → pending approval data
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
        # W10C-15: LLMRouter retired — every swarm call now goes through
        # the runtime.llm facade via LLMClientAdapter (duck-typed shim).
        self._swarm_llm_router = LLMClientAdapter(config=_swarm_config)
        self._swarm_blackboard = Blackboard(
            persist_path=self.data_dir / "swarm" / "blackboard.json"
        )
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
        await self._load_council_sessions()

        # Start periodic cleanup for zombie council sessions (every 15 min)
        self._cleanup_task = asyncio.create_task(self._periodic_council_cleanup())

        # Paperclip integration removed — never deployed a real backend.
        # Health endpoint still reports paperclip_connected: False as a status indicator.
        self._paperclip_connected = False
        log.info("NCL brain initialized (Paperclip adapter removed — degraded mode)")
        await self._log_event("startup", "NCL brain initialized (Paperclip adapter removed)")

    async def _run_council_with_pack_or_fallback(
        self,
        *,
        topic: str,
        prompt: str,
        trigger: str,
        members: Optional[list[str]] = None,
        session_id: Optional[str] = None,
    ) -> CouncilSession:
        """Try the universal council_pack path; fall back to ``spawn_council_session``
        on any failure.

        The pack path provides the 12 council improvements (MMR diversity,
        temporal split, contradiction surfacing, calibration preamble, peer
        review, 3-tier write-back, etc.). If anything in that chain throws
        — missing async-writer singleton, retriever crash, import error —
        we log and fall back to the legacy ``spawn_council_session`` so the
        pump pipeline NEVER regresses.

        Pattern mirrors ``scheduler._run_council_with_pack_or_fallback``.
        """
        try:
            from ..council_pack import run_council_with_pack
            from ..memory.retrieval import BM25Index, FusedRetriever

            store = self.memory_store
            if not getattr(store, "_bm25_index", None):
                store._bm25_index = BM25Index(store)
            fused = FusedRetriever(
                store,
                store._bm25_index,
                knowledge_graph=getattr(store, "_knowledge_graph", None),
            )

            # Best-effort acquire the async writer singleton (initialized in
            # scheduler.start()). If the scheduler hasn't started yet, the
            # singleton accessor raises — we treat that as "no write-back".
            async_writer = None
            try:
                from ..memory.async_writer import get_async_writer

                async_writer = get_async_writer()
            except Exception:
                async_writer = None

            # Source-authority learner singleton — None is acceptable, the
            # assembler treats it as a 1.0 multiplier (no adjustment).
            learner = None
            try:
                from ..feedback.source_authority_learner import get_learner

                learner = get_learner()
            except Exception:
                learner = None

            # Working context — owned by the scheduler. Stash it on the
            # brain via ``brain._working_context_ref`` if the caller wants
            # it; otherwise None (assembler degrades gracefully).
            working_context = getattr(self, "_working_context_ref", None)

            # Convert string members to enums same way spawn_council_session does.
            member_enums: Optional[list[CouncilMember]] = None
            if members:
                member_enums = []
                for m in members:
                    try:
                        member_enums.append(CouncilMember(m.lower()))
                    except ValueError:
                        log.warning(f"Unknown council member '{m}', skipping")

            result = await run_council_with_pack(
                council_engine=self.council_engine,
                topic=topic,
                base_prompt=prompt,
                fused_retriever=fused,
                working_context=working_context,
                learner=learner,
                async_writer=async_writer,
                members=member_enums,
                session_id=session_id,
                council_type=f"brain:{trigger}",
                peer_review=True,
            )
            session = result["session"]

            # Mirror spawn_council_session bookkeeping: persist + log + insights.
            async with self._council_sessions_lock:
                if len(self.council_sessions) >= self._COUNCIL_SESSIONS_MAX:
                    self._evict_oldest_council_sessions()
                self.council_sessions[session.session_id] = session
                await self._persist_council_sessions_unlocked()

            log.info(
                "[BRAIN-COUNCIL:PACK] %s session=%s pack_items=%d conflicts=%d "
                "cal_blocks=%d peer_reviews=%d writeback_gist_chars=%d",
                trigger,
                session.session_id,
                result["pack"].get("pack_size_items", 0),
                len(result["pack"].get("surfaced_conflicts", []) or []),
                len(result.get("calibrations") or []),
                len(result.get("peer_review") or []),
                len((result.get("writeback") or {}).get("gist") or ""),
            )
            return session
        except Exception as pack_err:
            log.warning(
                "[BRAIN-COUNCIL:PACK] pack path failed (%s) — falling back to "
                "legacy spawn_council_session",
                pack_err,
            )

        # Fallback — original behavior, unchanged.
        return await self.spawn_council_session(
            topic=topic,
            prompt=prompt,
            members=members,
            session_id=session_id,
        )

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

        # Step 2: Spawn council session via the universal council_pack pipeline
        # (MMR diversity, temporal split, contradiction surfacing, calibration,
        # peer review, 3-tier write-back). Falls back to legacy
        # ``spawn_council_session`` on any pack-path failure.
        try:
            session = await self._run_council_with_pack_or_fallback(
                topic=f"Pump: {prompt.intent}",
                prompt=council_prompt,
                trigger=f"pump:{prompt.urgency}",
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
                result["mandates"].append(
                    {
                        "mandate_id": mandate.mandate_id,
                        "pillar": mandate.pillar.value,
                        "title": mandate.title,
                        "priority": mandate.priority,
                        "objective": mandate.objective,
                        "success_criteria": mandate.success_criteria,
                    }
                )
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
                            log.error(f"Policy evaluation failed — fail-closed: {exc}")
                            allowed = False
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
                        log.warning(f"[approve] Invalid mandate transition for {mandate_id}: {e}")
                        mandate.updated_at = datetime.now(timezone.utc)

                    mandates_to_dispatch.append(
                        {
                            "mandate_id": mandate.mandate_id,
                            "pillar": mandate.pillar.value,
                            "title": mandate.title,
                            "priority": mandate.priority,
                        }
                    )

            await self._persist_mandates_unlocked()

        if not mandates_to_dispatch:
            return {
                "status": "no_mandates",
                "pump_id": pump_id,
                "blocked_by_policy": blocked_by_policy,
            }

        # Emergency-stop gate — refuse dispatch if engaged
        if await self._emergency_stop_engaged():
            log.warning(f"[approve] Emergency stop engaged — refusing dispatch for pump {pump_id}")
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

        # NCC dispatch retired 2026-05-23 (W8-A5); NCL is standalone. Mandates
        # remain persisted in-process via MandateStatus.ACTIVE. No external POST.
        # dispatch_result = await self._dispatch_to_ncc(mandates_to_dispatch)
        dispatch_result = None

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
                        log.warning(f"[reject] Invalid mandate transition for {mandate_id}: {e}")
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
        await self._mwp_write_stage(
            "01-intake",
            f"pump-{prompt.prompt_id}.json",
            {
                "pump_id": prompt.prompt_id,
                "intent": prompt.intent,
                "source": prompt.source,
                "urgency": prompt.urgency,
                "context": prompt.context or {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _mwp_analysis(self, prompt: PumpPrompt, council_prompt: str) -> None:
        """Stage 02 — Write analysis artifacts (council prompt + context)."""
        await self._mwp_write_stage(
            "02-analysis",
            f"analysis-{prompt.prompt_id}.json",
            {
                "pump_id": prompt.prompt_id,
                "council_prompt": council_prompt,
                "intent": prompt.intent,
                "urgency": prompt.urgency,
                "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _mwp_synthesis(self, session: CouncilSession) -> None:
        """Stage 03 — Write council transcript + synthesis + consensus score."""
        rounds_data = []
        for rnd in session.rounds:
            rounds_data.append(
                {
                    "round_number": rnd.round_number,
                    "round_type": rnd.round_type,
                    "responses": rnd.responses,
                    "scores": rnd.scores,
                }
            )

        await self._mwp_write_stage(
            "03-synthesis",
            f"synthesis-{session.session_id}.json",
            {
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
                }
                if session.consensus_score
                else None,
                "recommendations": session.recommendations,
                "dissents": session.dissents,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            },
        )

    async def _mwp_mandate_draft(self, mandates_data: list[dict], pump_id: str) -> None:
        """Stage 04 — Write extracted mandate drafts."""
        await self._mwp_write_stage(
            "04-mandate-draft",
            f"mandates-{pump_id}.json",
            {
                "pump_id": pump_id,
                "mandate_count": len(mandates_data),
                "mandates": [
                    {
                        "pillar": m["pillar"].value
                        if hasattr(m["pillar"], "value")
                        else str(m["pillar"]),
                        "title": m["title"],
                        "objective": m["objective"],
                        "priority": m["priority"],
                        "success_criteria": m.get("success_criteria", []),
                    }
                    for m in mandates_data
                ],
                "drafted_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _mwp_review(
        self, prompt: PumpPrompt, session: CouncilSession, mandates: list[dict]
    ) -> None:
        """Stage 05 — Write final approval/review package."""
        await self._mwp_write_stage(
            "05-review",
            f"review-{prompt.prompt_id}.json",
            {
                "pump_id": prompt.prompt_id,
                "intent": prompt.intent,
                "urgency": prompt.urgency,
                "council_session_id": session.session_id,
                "consensus_met": session.consensus_score.threshold_met
                if session.consensus_score
                else False,
                "consensus_pct": session.consensus_score.agreement_pct
                if session.consensus_score
                else 0,
                "mandates_generated": len(mandates),
                "mandates": mandates,
                "dissents": session.dissents,
                "review_status": "auto_approved"
                if (session.consensus_score and session.consensus_score.threshold_met)
                else "needs_natrix_review",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

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
            f"1. Which mandate(s) should NCL pursue in-process? "
            f"(BRS/AAC/NCC pillars retired 2026-05-23 — NCL is standalone.)\n"
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
        text_lower = text.lower()  # noqa: F841

        # Try to parse structured mandate blocks from council output

        # Look for PILLAR: mentions
        # BRS/AAC retired 2026-05-23; NCC repo also removed from this
        # machine. NCL is standalone — every mandate targets NCL itself
        # (in-process persistence + Brain-internal loops). Legacy
        # "ncc"/"brs"/"aac" tags in council output are folded to NCL so
        # we don't silently drop council-proposed mandates.
        pillar_map = {
            "ncl": PillarType.NCL,
            "ncc": PillarType.NCL,
            "brs": PillarType.NCL,
            "aac": PillarType.NCL,
        }

        # Pattern: PILLAR: NCL ... TITLE: ... OBJECTIVE: ... PRIORITY: N
        blocks = re.split(r"(?:^|\n)(?=(?:PILLAR|Pillar|pillar)\s*:)", text)
        for block in blocks:
            if not block.strip():
                continue
            pillar_match = re.search(r"(?:PILLAR|Pillar|pillar)\s*:\s*(\w+)", block)
            title_match = re.search(r"(?:TITLE|Title|title)\s*:\s*(.+?)(?:\n|$)", block)
            obj_match = re.search(r"(?:OBJECTIVE|Objective|objective)\s*:\s*(.+?)(?:\n|$)", block)
            pri_match = re.search(r"(?:PRIORITY|Priority|priority)\s*:\s*(\d+)", block)
            criteria_matches = re.findall(
                r"(?:SUCCESS_CRITERIA|criteria)\s*:\s*(.+?)(?:\n|$)", block, re.IGNORECASE
            )

            if pillar_match:
                pillar_key = pillar_match.group(1).lower().strip()
                if pillar_key in pillar_map:
                    mandates.append(
                        {
                            "pillar": pillar_map[pillar_key],
                            "title": title_match.group(1).strip()
                            if title_match
                            else f"Mandate from pump {prompt.prompt_id}",
                            "objective": obj_match.group(1).strip() if obj_match else prompt.intent,
                            "priority": min(10, max(1, int(pri_match.group(1))))
                            if pri_match
                            else (8 if prompt.urgency == "critical" else 5),
                            "success_criteria": [c.strip() for c in criteria_matches]
                            if criteria_matches
                            else [],
                        }
                    )

        # Fallback: if no structured mandates found, create one from intent
        if not mandates:
            # All mandates target NCL itself. BRS/AAC retired 2026-05-23
            # and the NCC repo is no longer on this machine — there is no
            # downstream pillar to route to. Mandates persist in-process.
            target = PillarType.NCL

            mandates.append(
                {
                    "pillar": target,
                    "title": f"Directive: {prompt.intent[:80]}",
                    "objective": prompt.intent,
                    "priority": 8
                    if prompt.urgency == "critical"
                    else 6
                    if prompt.urgency == "high"
                    else 5,
                    "success_criteria": session.recommendations[:5]
                    if session.recommendations
                    else [],
                }
            )

        return mandates

    async def _dispatch_to_ncc(self, mandates: list[dict]) -> dict | None:
        """Vestigial no-op. NCC repo absent from this machine since
        2026-05-23. Signature preserved for legacy callers (see
        approve_and_dispatch). NCL is standalone — mandates persist
        in-process via MandateStatus.ACTIVE."""
        # NCC repo absent from this machine since 2026-05-23. No-op preserved for legacy callers.
        return None

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
                except ValueError as exc:
                    # Transition not allowed from current state — audit and bump timestamp
                    log.warning(
                        f"[dispatch] Cannot transition {mandate_id} ({mandate.status.value}) → FAILED: {exc}"  # noqa: E501
                    )
                    mandate.updated_at = datetime.now(timezone.utc)
                await self._persist_mandates_unlocked()

    async def spawn_council_session(
        self,
        topic: str,
        prompt: str,
        members: Optional[list[str]] = None,
        session_id: Optional[str] = None,
    ) -> CouncilSession:
        """
        Spawn a new council debate session.

        Args:
            topic: Debate topic
            prompt: Chair's prompt
            members: Council member names (strings converted to CouncilMember enums)
            session_id: Optional pre-generated session ID (used by API to guarantee
                        the returned ID matches the one stored in council_sessions)

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

        session = await self.council_engine.spawn_session(
            topic, prompt, member_enums, session_id=session_id
        )
        async with self._council_sessions_lock:
            # Evict oldest sessions when at capacity
            if len(self.council_sessions) >= self._COUNCIL_SESSIONS_MAX:
                self._evict_oldest_council_sessions()
            self.council_sessions[session.session_id] = session
            await self._persist_council_sessions_unlocked()

        await self._log_event(
            "council_spawned",
            f"Council session on {topic}",
            {"session_id": session.session_id},
        )

        # Run debate. Always persist the final state — even on partial failure
        # the engine returns the session with status=COMPLETE/FAILED + any
        # rounds collected. Previously the file was written ONLY at spawn
        # (status=DEBATING) so every session stayed forever stuck "debating".
        # Quality metric: count completed vs failed sessions for telemetry.
        try:
            session = await self.council_engine.run_debate(session)
        except Exception as e:
            log.exception(f"[spawn_council_session] run_debate crashed: {e}")
            session.status = CouncilStatus.FAILED
            session.completed_at = datetime.now(timezone.utc)
            if not session.synthesis:
                session.synthesis = f"Debate crashed: {type(e).__name__}: {e}"
            self._council_quality.setdefault("failed", 0)
            self._council_quality["failed"] += 1
        else:
            self._council_quality.setdefault(session.status.value, 0)
            self._council_quality[session.status.value] += 1

        # CRITICAL: re-persist final state so on-disk file moves
        # debating → completed / failed.  Without this the file is stale
        # forever (the root cause of every session being stuck "debating"
        # since 2026-05-17).
        async with self._council_sessions_lock:
            self.council_sessions[session.session_id] = session
            await self._persist_council_sessions_unlocked()

        await self._log_event(
            "council_completed",
            f"Council session {session.session_id} completed",
            {
                "topic": topic,
                "consensus": session.consensus,
                "recommendations": session.recommendations,
                "status": session.status.value,
            },
        )

        # Store insights in memory — only if we have real consensus, not a
        # crash message. Avoids polluting memory with "Synthesis error" rows.
        if session.consensus and session.status == CouncilStatus.COMPLETE:
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
        status: MandateStatus = MandateStatus.PENDING_APPROVAL,
    ) -> Mandate:
        """
        Create a new mandate for a pillar.

        Args:
            pillar: Target pillar (NCC only; BRS/AAC retired 2026-05-23)
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
        # through the policy kernel. FAIL CLOSED on any error to prevent
        # silent governance bypass (was fail-open prior to 2026-05-15 audit).
        if status == MandateStatus.ACTIVE and self.policy_kernel is not None:
            try:
                allowed = await self._policy_allows_dispatch(mandate)
            except Exception as exc:
                log.error(
                    f"[create_mandate] PolicyKernel raised; FAIL CLOSED for mandate "
                    f"{mandate.mandate_id}: {exc}"
                )
                allowed = False
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

        await self._log_event(
            "mandate_created",
            f"Mandate {mandate.mandate_id} for {pillar.value}",
            {"mandate_id": mandate.mandate_id, "priority": priority},
        )

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
                target=mandate.pillar.value
                if hasattr(mandate.pillar, "value")
                else str(mandate.pillar),
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
                log.warning(
                    f"[governance] PolicyKernel blocked mandate {mandate.mandate_id}: {reason}"
                )
            return allowed
        except Exception as e:
            log.error(f"[governance] Policy check error; FAIL CLOSED: {e}")
            return False  # Fail-closed on errors (audit 2026-05-15)

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
            log.error(
                f"[governance] Emergency stop check error; FAIL CLOSED (treat as engaged): {e}"
            )
            return True  # Fail-closed on errors (audit 2026-05-15)

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
                log.warning(f"[complete] Invalid mandate transition for {mandate_id}: {e}")
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
        units = await _maybe_indexed_search(
            self.memory_store,
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
        # Gather signals from memory — lowered threshold from 50.0 to 25.0
        # so intelligence-hydrated signals and council results aren't filtered out
        memory_results = await self.query_memory(
            tags=[topic.lower()],
            importance_threshold=25.0,
            days_back=14,  # Extended from 7 to 14 days for more signal accumulation
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

        # Fallback: if no tag-matched signals, try semantic search
        if not signals and hasattr(self.memory_store, "semantic_search"):
            try:
                semantic_results = await self.memory_store.semantic_search(
                    query=topic,
                    limit=10,
                )
                for unit in semantic_results if isinstance(semantic_results, list) else []:
                    content = unit.get("content", "") if isinstance(unit, dict) else ""
                    importance = (
                        float(unit.get("importance", 40.0)) if isinstance(unit, dict) else 40.0
                    )
                    if not content:
                        continue
                    signals.append(
                        InsightSignal(
                            signal_id=str(uuid.uuid4()),
                            source_platform="memory_semantic",
                            content=content[:500],
                            importance_score=importance,
                            relevance=min(1.0, importance / 100.0),
                            novelty=0.5,
                            actionability=0.5,
                            source_authority=0.6,
                            time_sensitivity=0.4,
                            timestamp=datetime.now(timezone.utc),
                            tags=[topic.lower()],
                        )
                    )
                if signals:
                    log.info(
                        f"[prediction] Tag search empty, semantic fallback found {len(signals)} signals for '{topic}'"  # noqa: E501
                    )
            except Exception as e:
                log.warning(f"[prediction] Semantic search fallback failed: {e}")

        if not signals:
            return {
                "prediction_id": str(uuid.uuid4()),
                "topic": topic,
                "consensus": "no data — no memory signals found for this topic. Run an intelligence brief first to populate signals.",  # noqa: E501
                "confidence": 0.0,
                "convergence": [],
                "warnings": [
                    f"No memory units found for topic '{topic}' in the past 14 days",
                    "Tip: Run POST /v1/intelligence/brief to collect signals, then retry prediction",  # noqa: E501
                ],
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

    async def dispatch_research(
        self, query: str, depth: str = "standard", priority: int = 5
    ) -> dict:
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
        active_mandates = [
            m
            for m in self.mandates.values()
            if m.status in (MandateStatus.ACTIVE, MandateStatus.IN_PROGRESS)
        ]
        pending_approval = [
            m for m in self.mandates.values() if m.status == MandateStatus.PENDING_APPROVAL
        ]
        memory_stats = (
            await self.memory_store.get_stats() if hasattr(self.memory_store, "get_stats") else {}
        )

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

        uptime_seconds = (
            (datetime.now(timezone.utc) - self._started_at).total_seconds()
            if self._started_at
            else 0
        )
        return {
            "status": status,
            "service": "ncl-brain",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_hours": round(uptime_seconds / 3600, 1),
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
        log.info(
            f"[council_sessions] Evicted {evict_count} oldest sessions (limit={self._COUNCIL_SESSIONS_MAX})"  # noqa: E501
        )

    async def cleanup_council_sessions(self, max_age_hours: int = 1) -> int:
        """
        Remove council sessions older than max_age_hours.

        Async-safe. Returns the number of sessions removed.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
        removed = 0
        async with self._council_sessions_lock:
            stale = [
                sid
                for sid, s in self.council_sessions.items()
                if s.completed_at and s.completed_at.timestamp() < cutoff
            ]
            for sid in stale:
                del self.council_sessions[sid]
                removed += 1
        if removed:
            log.info(
                f"[council_sessions] Cleaned up {removed} sessions older than {max_age_hours}h"
            )
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

        # SQLite double-write (flag-gated, never blocks the JSON write).
        # W10B-1: routed through the unified DoubleWriteHook — the hook
        # owns the env-flag check, lazy store acquisition, batch
        # execute_many call, and warn-once flap suppression. The W10A-4
        # pillar-enum guard now lives inside _build_mandate_row (returns
        # None for invalid rows; the hook skips them).
        await self._sqlite_persist_mandates(self.mandates)

    async def _sqlite_persist_mandates(self, mandates_dict: dict) -> None:
        """
        Mirror the in-memory mandates dict into the SQLite `mandates` table.

        W10B-1 (2026-05-24): this method now delegates to a shared
        ``DoubleWriteHook`` instance. The row-building logic (incl. the
        W10A-4 pillar-enum guard) lives in ``_build_mandate_row``;
        ``DoubleWriteHook.try_write_many`` runs the env-flag check,
        lazy-acquires the SqliteStore, calls ``execute_many`` with the
        compiled-once INSERT OR REPLACE SQL, and swallows any backend
        failure with a one-shot warning. The JSON file remains the
        source of truth.

        Kept as a method (not inlined into the caller) so the existing
        test harness can call it directly via descriptor binding.
        """
        if not mandates_dict:
            return
        await self._mandates_hook().try_write_many(mandates_dict.values())

    @staticmethod
    def _build_mandate_row(m):
        """Map one Mandate model to the mandates-table column tuple.

        Returns ``None`` to skip (DoubleWriteHook convention) when:
          * model_dump() raises, or
          * the W10A-4 pillar-enum guard rejects the row.
        """
        try:
            dump = m.model_dump()
        except Exception:
            return None

        def _enum_value(v):
            # Pydantic model_dump() returns the Enum instance for str-Enum
            # fields; coerce to the underlying string so SQLite stores the
            # value ("draft") not the repr ("MandateStatus.DRAFT").
            return v.value if hasattr(v, "value") else v

        status_v = _enum_value(dump.get("status"))
        pillar_v = _enum_value(dump.get("pillar"))
        mandate_id = dump.get("mandate_id")

        # W10A-4: pillar enum guard. The JSON load path validates pillar
        # against PillarType via Pydantic, but the SQLite write path
        # historically wrote raw values without re-validation. If a
        # forged mandate dict landed in self.mandates, an invalid pillar
        # row could persist in SQLite and (after a read-flag flip)
        # become authoritative. Skip such rows here.
        valid_pillars = {p.value for p in PillarType}
        if pillar_v not in valid_pillars:
            log.warning(
                "[mandates] skipping row with invalid pillar=%r mandate_id=%s",
                pillar_v,
                mandate_id,
            )
            return None

        return (
            str(mandate_id),
            str(pillar_v) if pillar_v is not None else None,
            int(dump["priority"]) if dump.get("priority") is not None else None,
            dump.get("title"),
            dump.get("objective"),
            json.dumps(
                dump.get("success_criteria") or [], default=str, separators=(",", ":")
            ),
            str(dump["deadline"]) if dump.get("deadline") else None,
            json.dumps(dump.get("resources") or {}, default=str, separators=(",", ":")),
            str(status_v) if status_v is not None else "draft",
            int(dump.get("version", 0) or 0),
            str(dump["created_at"])
            if dump.get("created_at")
            else datetime.now(timezone.utc).isoformat(),
            str(dump["updated_at"])
            if dump.get("updated_at")
            else datetime.now(timezone.utc).isoformat(),
            str(dump["source_pump_id"]) if dump.get("source_pump_id") else None,
            json.dumps(
                dump.get("status_history") or [], default=str, separators=(",", ":")
            ),
            json.dumps(dump, default=str, separators=(",", ":")),
        )

    def _mandates_hook(self):
        """Lazily build (and cache) the DoubleWriteHook for mandates."""
        hook = getattr(self, "_mandates_dw_hook", None)
        if hook is not None:
            return hook
        from runtime.persistence import DoubleWriteHook

        hook = DoubleWriteHook(
            env_flag="NCL_MANDATES_SQLITE",
            table="mandates",
            columns=(
                "mandate_id", "pillar", "priority", "title", "objective",
                "success_criteria", "deadline", "resources", "status",
                "version", "created_at", "updated_at", "source_pump_id",
                "status_history", "payload",
            ),
            build_row=NCLBrain._build_mandate_row,
            conflict_strategy="replace",
            log_prefix="[mandates]",
        )
        self._mandates_dw_hook = hook
        return hook

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
                    log.info(
                        f"[load_state] Loaded {len(self._pending_dispatches)} pending dispatches"
                    )
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

    def get_pending_dispatches(self) -> dict:
        """Public snapshot of pending-dispatch state.

        Returns a shallow copy so callers cannot mutate brain state directly.
        Acquires no async lock (read-only snapshot of an OrderedDict reference);
        for write operations callers must go through approve/reject helpers.
        """
        return dict(self._pending_dispatches)

    # -------------------------------------------------------------------
    # Council Sessions Persistence
    # -------------------------------------------------------------------

    async def _load_council_sessions(self) -> None:
        """Load council sessions from disk on startup."""
        if not self._council_sessions_file.exists():
            return
        try:
            async with aiofiles.open(self._council_sessions_file) as f:
                content = await f.read()
            if not content:
                return
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError) as exc:
                log.error(f"[load_state] Corrupt council_sessions file — skipping: {exc}")
                return
            if isinstance(data, dict):
                for sid, sess_dict in data.items():
                    try:
                        self.council_sessions[sid] = CouncilSession(**sess_dict)
                    except Exception as exc:
                        log.error(f"[load_state] Skipping malformed council session {sid}: {exc}")
                while len(self.council_sessions) > self._COUNCIL_SESSIONS_MAX:
                    self.council_sessions.popitem(last=False)
                log.info(f"[load_state] Loaded {len(self.council_sessions)} council sessions")
        except OSError as exc:
            log.error(f"[load_state] Could not read council_sessions file: {exc}")

    async def _persist_council_sessions_unlocked(self) -> None:
        """Persist council sessions to disk. Caller must hold _council_sessions_lock."""
        try:
            snapshot = {sid: sess.model_dump() for sid, sess in self.council_sessions.items()}
            payload = json.dumps(snapshot, default=str, indent=2)
            tmp_path = self._council_sessions_file.with_suffix(".json.tmp")
            await asyncio.to_thread(
                self._atomic_write_json, tmp_path, self._council_sessions_file, payload
            )
        except Exception as exc:
            log.error(f"[persist] Failed to save council_sessions: {exc}")

    # -------------------------------------------------------------------
    # Periodic Council Session Cleanup
    # -------------------------------------------------------------------

    async def _periodic_council_cleanup(self) -> None:
        """Background task: clean up zombie council sessions every 15 minutes."""
        while True:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[COUNCIL-CLEANUP] Emergency stop active — halting loop")
                break
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
