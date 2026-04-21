"""Main NCL brain service."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiofiles

log = logging.getLogger("ncl.brain")

from .models import (
    PumpPrompt,
    Mandate,
    MandateStatus,
    CouncilSession,
    FeedbackReport,
    PillarType,
)
from .council import CouncilEngine
from ..memory import MemoryStore
from ..awarebot import Scanner, FuturePredictor
from ..paperclip_adapter import PaperclipClient


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
        paperclip_port: int = 8765,
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

        # In-memory state
        self.mandates: dict[str, Mandate] = {}
        self.council_sessions: dict[str, CouncilSession] = {}
        self._pending_dispatches: dict[str, dict] = {}  # pump_id → pending approval data

    async def init(self) -> None:
        """Initialize brain on startup."""
        # Load existing state
        await self._load_state()

        # Register with Paperclip
        self._paperclip_connected = False
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
        import httpx
        import os

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

        async with httpx.AsyncClient(timeout=10.0) as client:
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
        self._pending_dispatches[prompt.prompt_id] = {
            "mandates": result["mandates"],
            "council_session_id": session.session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

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
        pending = self._pending_dispatches.get(pump_id)
        if not pending:
            return {"error": f"No pending dispatch found for pump {pump_id}"}

        mandates_to_dispatch = []

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

                # Promote from PENDING_APPROVAL → ACTIVE
                mandate.status = MandateStatus.ACTIVE
                mandate.updated_at = datetime.now(timezone.utc)

                mandates_to_dispatch.append({
                    "mandate_id": mandate.mandate_id,
                    "pillar": mandate.pillar.value,
                    "title": mandate.title,
                    "priority": mandate.priority,
                })

        await self._persist_mandates()

        if not mandates_to_dispatch:
            return {"status": "no_mandates", "pump_id": pump_id}

        # NOW dispatch to NCC — only after NATRIX approval
        dispatch_result = await self._dispatch_to_ncc(mandates_to_dispatch)

        # Clean up pending
        del self._pending_dispatches[pump_id]

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
        pending = self._pending_dispatches.get(pump_id)
        if not pending:
            return {"error": f"No pending dispatch found for pump {pump_id}"}

        # Mark all pending mandates as CANCELLED
        for m in pending["mandates"]:
            mandate_id = m.get("mandate_id", "")
            mandate = self.mandates.get(mandate_id)
            if mandate:
                mandate.status = MandateStatus.CANCELLED
                mandate.updated_at = datetime.now(timezone.utc)

        await self._persist_mandates()
        del self._pending_dispatches[pump_id]

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
        import re

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
            if any(w in text_lower for w in ["revenue", "ship", "product", "earn", "digital-labour", "freelance"]):
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
        import httpx
        import os

        ncc_host = os.getenv("NCC_HOST", "http://localhost")
        ncc_port = int(os.getenv("NCC_PORT", "8765"))
        url = f"{ncc_host}:{ncc_port}/mandate/intake"

        dispatched = []
        failed = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for m in mandates:
                    if "error" in m:
                        continue
                    try:
                        # Build NCC-compatible MandateRequest payload
                        from datetime import timedelta
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

                        resp = await client.post(url, json={
                            "mandate_id": m.get("mandate_id", ""),
                            "title": m.get("title", "Untitled mandate"),
                            "description": m.get("objective", m.get("title", "Mandate from NCL")),
                            "deadline": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                            "priority": priority_level,
                            "target_pillar": target_list,
                            "success_criteria": m.get("success_criteria", ["Complete as directed"]),
                            "tags": ["ncl-generated", "strike-point"],
                        })
                        if resp.status_code < 400:
                            dispatched.append(m.get("mandate_id", m.get("title")))
                        else:
                            failed.append({"mandate": m.get("title"), "error": f"HTTP {resp.status_code}"})
                    except Exception as e:
                        failed.append({"mandate": m.get("title"), "error": str(e)})
        except Exception as e:
            return {"status": "ncc_unreachable", "error": str(e)}

        return {
            "status": "dispatched",
            "dispatched": dispatched,
            "failed": failed,
        }

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
        from .models import CouncilMember

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

        self.mandates[mandate.mandate_id] = mandate
        await self._persist_mandates()

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

        mandate.status = MandateStatus.COMPLETED
        mandate.updated_at = datetime.now(timezone.utc)
        await self._persist_mandates()

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

        # Run prediction
        # (simplified - would use actual signals from Awarebot in production)
        from ..ncl_brain.models import InsightSignal

        signals = [
            InsightSignal(
                signal_id=str(uuid.uuid4()),
                source_platform="memory",
                content=f"Memory signal about {topic}",
                importance_score=70.0,
                relevance=0.8,
                novelty=0.6,
                actionability=0.7,
                source_authority=0.8,
                time_sensitivity=0.6,
                timestamp=datetime.now(timezone.utc),
                tags=[topic.lower()],
            )
        ]

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

    async def health_check(self) -> dict:
        """
        Health check endpoint — enriched for MATRIX MONITOR.

        Returns:
            Health status dict with all data MATRIX MONITOR needs
        """
        active_mandates = [m for m in self.mandates.values() if m.status in (MandateStatus.ACTIVE, MandateStatus.IN_PROGRESS)]
        memory_stats = await self.memory_store.get_stats() if hasattr(self.memory_store, "get_stats") else {}

        return {
            "status": "healthy",
            "service": "ncl-brain",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_pct": 100.0,
            # MATRIX MONITOR fields
            "active_mandates": len(active_mandates),
            "mandates_total": len(self.mandates),
            "council_sessions": len(self.council_sessions),
            "memory_units": memory_stats.get("total_units", 0),
            "key_metric": len(active_mandates),
            "key_metric_label": "active_mandates",
            "paperclip_connected": getattr(self, "_paperclip_connected", False),
        }

    async def shutdown(self) -> None:
        """Shutdown brain on exit."""
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
        from .models import NCLEvent, EventType as ET

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

        # Write v1 schema to NDJSON (backwards-compatible dict format)
        async with aiofiles.open(self.events_file, "a") as f:
            await f.write(ncl_event.to_ndjson() + "\n")

        # Log to Paperclip
        try:
            await self.paperclip.log_activity(
                activity_type=event_type,
                description=description,
                agent_name="NCL",
                metadata=metadata,
            )
        except Exception:
            pass

        return ncl_event.event_id

    async def _load_state(self) -> None:
        """Load mandates from disk on startup."""
        if self.mandates_file.exists():
            async with aiofiles.open(self.mandates_file) as f:
                content = await f.read()
                if content:
                    mandates_data = json.loads(content)
                    for mandate_dict in mandates_data:
                        mandate = Mandate(**mandate_dict)
                        self.mandates[mandate.mandate_id] = mandate

    async def _persist_mandates(self) -> None:
        """Persist mandates to disk."""
        async with aiofiles.open(self.mandates_file, "w") as f:
            mandates_data = [m.model_dump() for m in self.mandates.values()]
            await f.write(json.dumps(mandates_data, default=str, indent=2))
