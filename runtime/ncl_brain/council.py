"""
Council Debate Engine for NCL — Hybrid Delphi-MAD Protocol.

Implements a structured multi-round debate protocol fusing:
- Delphi Method: Anonymous iterative rounds with controlled feedback
- Nominal Group Technique: Silent generation → round-robin → scoring → convergence
- Multi-Agent Debate (MAD): Role-assigned agents with moderator synthesis
- Robert's Rules: Motion → debate → rebuttal → vote structure

Protocol (Delphi-MAD):
  Round 1 — POSITION:    Each member states position from their assigned role
  Round 2 — REBUTTAL:    Each member responds to others' positions (cross-examination)
  Round 3 — CONVERGENCE: Members update positions after seeing rebuttals
  SYNTHESIS:              Claude (chair) synthesizes all rounds into final output
  SCORING:                Consensus detection via agreement percentage + confidence weighting

Members (6 + Chair):
  Claude  — CHAIR:      Moderates all rounds, synthesizes, judges consensus
  Grok    — STRATEGIST: Bold moves, first-strike intuition, contrarian views
  Gemini  — ANALYST:    Data-driven, structured analysis, Google intelligence
  Perplexity — RESEARCHER: Fact-checking, source-backed, real-time web intelligence
  GPT     — CREATIVE:   Lateral thinking, alternative approaches, edge cases
  Copilot — ENGINEER:   Technical feasibility, implementation cost, architecture

Fallback: Ollama local models (qwen3:8b, qwen3:32b) when APIs are unreachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from .models import (
    ConsensusScore,
    CouncilMember,
    CouncilRole,
    CouncilSession,
    CouncilStatus,
    DebateRound,
)


log = logging.getLogger("ncl.council")

# ---------------------------------------------------------------------------
# Cost configuration — overrideable via environment variables (cents per call)
# ---------------------------------------------------------------------------


def _cost_cfg() -> dict[str, int]:
    """
    Build cost-per-call config from environment variables.

    Each key can be overridden by NCL_COST_<MEMBER> (e.g. NCL_COST_CLAUDE=7).
    Values are in cents. Defaults match the original hardcoded estimates.
    """
    defaults = {
        "claude": 5,
        "grok": 4,
        "gemini": 1,
        "perplexity": 3,
        "gpt": 5,
        "copilot": 5,
        "ollama": 0,
    }
    return {
        member: int(os.environ.get(f"NCL_COST_{member.upper()}", default))
        for member, default in defaults.items()
    }


# Module-level singleton — re-read from env at import time so tests can patch env.
COST_CONFIG: dict[str, int] = _cost_cfg()

# ---------------------------------------------------------------------------
# Role Prompting System — Each member gets a unique persona + lens
# ---------------------------------------------------------------------------

ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    CouncilRole.CHAIR: (
        "You are the CHAIR of the NCL Council. You moderate debate, "
        "ensure all perspectives are heard, synthesize arguments into actionable consensus, "
        "and make final judgments when the council cannot agree. You are impartial but decisive. "
        "You identify the strongest arguments, flag weak reasoning, and produce clear mandates."
    ),
    CouncilRole.STRATEGIST: (
        "You are the STRATEGIST on the NCL Council. Your lens is bold, "
        "first-strike intuition. You think in terms of competitive advantage, speed-to-market, "
        "asymmetric bets, and opportunity cost. You challenge safe thinking and push for decisive "
        "action. You ask: 'What's the 10x move here?' and 'What are we missing that competitors "
        "will exploit?' You are contrarian when the group is too cautious."
    ),
    CouncilRole.ANALYST: (
        "You are the ANALYST on the NCL Council. Your lens is data-driven, "
        "structured analysis. You break problems into quantifiable components, assess risk with "
        "probabilities, and demand evidence for claims. You ask: 'What does the data show?' and "
        "'What are the measurable success criteria?' You flag when decisions are based on "
        "assumption rather than evidence. You provide structured frameworks."
    ),
    CouncilRole.RESEARCHER: (
        "You are the RESEARCHER on the NCL Council. Your lens is fact-checking, "
        "source verification, and real-time intelligence. You ground the discussion in what is "
        "actually true and currently happening in the market. You ask: 'What are the latest "
        "developments?' and 'Does this align with current market reality?' You flag claims that "
        "need verification and provide counter-evidence when available."
    ),
    CouncilRole.CREATIVE: (
        "You are the CREATIVE on the NCL Council. Your lens is lateral thinking, "
        "alternative approaches, and edge cases. You find solutions the group hasn't considered, "
        "challenge framing assumptions, and propose unconventional paths. You ask: 'What if we "
        "approached this completely differently?' and 'What are the second-order effects nobody "
        "is considering?' You are the voice of innovation and managed chaos."
    ),
    CouncilRole.ENGINEER: (
        "You are the ENGINEER on the NCL Council. Your lens is technical "
        "feasibility, implementation cost, and architectural soundness. You evaluate whether "
        "proposals can actually be built, how long they'll take, and what technical debt they'll "
        "create. You ask: 'Can we actually ship this?' and 'What's the simplest architecture "
        "that works?' You flag technically impossible proposals and suggest pragmatic alternatives. "  # noqa: E501
        "You think about Mac Mini M4 Pro constraints, Apple Silicon optimization, and local-first "
        "architecture."
    ),
}

# Default role assignments (member → role)
DEFAULT_ROLE_MAP: dict[CouncilMember, CouncilRole] = {
    CouncilMember.CLAUDE: CouncilRole.CHAIR,
    CouncilMember.GROK: CouncilRole.STRATEGIST,
    CouncilMember.GEMINI: CouncilRole.ANALYST,
    CouncilMember.PERPLEXITY: CouncilRole.RESEARCHER,
    CouncilMember.GPT: CouncilRole.CREATIVE,
    CouncilMember.COPILOT: CouncilRole.ENGINEER,
}


# ---------------------------------------------------------------------------
# Round-Specific Prompting
# ---------------------------------------------------------------------------


def _build_round_prompt(
    round_type: str,
    round_number: int,
    topic: str,
    base_prompt: str,
    role: CouncilRole,
    member_name: str,
    previous_responses: dict[str, str] | None = None,
    round_history: list[DebateRound] | None = None,
) -> str:
    """Build a round-specific prompt for a council member."""

    system = ROLE_SYSTEM_PROMPTS.get(role, "You are a council member.")

    if round_type == "position":
        # Round 1: State initial position
        return (
            f"{system}\n\n"
            f"COUNCIL DEBATE — Round {round_number}: INITIAL POSITION\n"
            f"Topic: {topic}\n\n"
            f"DIRECTIVE FROM NATRIX:\n{base_prompt}\n\n"
            f"As the {role.value.upper()}, state your position on this directive.\n"
            f"Structure your response as:\n"
            f"POSITION: Your core stance (1-2 sentences)\n"
            f"REASONING: Key arguments supporting your position\n"
            f"RISKS: What could go wrong\n"
            f"RECOMMENDATION: Specific action items with PILLAR, TITLE, OBJECTIVE, PRIORITY\n"
            f"CONFIDENCE: Your confidence level (0-100)\n"
        )

    elif round_type == "rebuttal":
        # Round 2: Cross-examine other positions
        others_text = ""
        if previous_responses:
            for name, resp in previous_responses.items():
                if name != member_name:
                    # Truncate to keep prompt manageable
                    others_text += f"\n[{name.upper()}]: {resp[:600]}\n"

        return (
            f"{system}\n\n"
            f"COUNCIL DEBATE — Round {round_number}: REBUTTAL\n"
            f"Topic: {topic}\n\n"
            f"Your initial position was:\n{previous_responses.get(member_name, '(no response)')[:400]}\n\n"  # noqa: E501
            f"Other council members' positions:{others_text}\n\n"
            f"As the {role.value.upper()}, respond to the other members' positions.\n"
            f"You MUST:\n"
            f"1. Identify the strongest argument from another member and explain why\n"
            f"2. Challenge the weakest argument from another member with evidence\n"
            f"3. State whether you AGREE, DISAGREE, or PARTIALLY AGREE with each\n"
            f"4. Update your RECOMMENDATION if your position has shifted\n"
            f"5. State your updated CONFIDENCE (0-100)\n"
        )

    elif round_type == "convergence":
        # Round 3: Final position after seeing all rebuttals
        r1_text = ""
        r2_text = ""
        if round_history:
            for rnd in round_history:
                if rnd.round_type == "position":
                    for name, resp in rnd.responses.items():
                        r1_text += f"\n[{name}] R1: {resp[:300]}"
                elif rnd.round_type == "rebuttal":
                    for name, resp in rnd.responses.items():
                        r2_text += f"\n[{name}] R2: {resp[:300]}"

        return (
            f"{system}\n\n"
            f"COUNCIL DEBATE — Round {round_number}: FINAL CONVERGENCE\n"
            f"Topic: {topic}\n\n"
            f"ROUND 1 POSITIONS (summary):{r1_text}\n\n"
            f"ROUND 2 REBUTTALS (summary):{r2_text}\n\n"
            f"This is the FINAL round. As the {role.value.upper()}, provide your definitive position.\n"  # noqa: E501
            f"Structure your response as:\n"
            f"FINAL_POSITION: Your definitive stance after hearing all arguments\n"
            f"AGREE_WITH: Which members/arguments you agree with and why\n"
            f"DISSENT: Any remaining disagreements (or 'None')\n"
            f"MANDATE: Your recommended mandate(s) with PILLAR, TITLE, OBJECTIVE, PRIORITY, SUCCESS_CRITERIA\n"  # noqa: E501
            f"CONFIDENCE: Your final confidence (0-100)\n"
        )

    return f"{system}\n\n{base_prompt}"


# ---------------------------------------------------------------------------
# Council Engine
# ---------------------------------------------------------------------------


class CouncilEngine:
    """
    Multi-AI council debate system — Hybrid Delphi-MAD Protocol.

    Claude as permanent chair/moderator. 5 debaters (Grok, Gemini, Perplexity,
    GPT, Copilot) with assigned roles. 3-round structured debate with consensus
    scoring and synthesis.

    Paperclip Integration:
    - Session spawn → Paperclip issue created (tracks council lifecycle)
    - Each API call → cost-event reported per member
    - Synthesis complete → issue updated with consensus score
    - Low consensus (<70%) → approval request for NATRIX review
    - Session close → activity logged

    MWP Integration:
    - Receives artifacts from brain.py which writes to MWP output directories
    - Council engine focuses on debate logic; brain.py handles MWP file I/O
    """

    # Estimated cost per API call in cents (for Paperclip cost tracking).
    # Values are loaded from COST_CONFIG which reads NCL_COST_<MEMBER> env vars,
    # so this property always reflects the current config without a restart.
    @property
    def COST_ESTIMATES_CENTS(self) -> dict[str, int]:  # noqa: N802
        return COST_CONFIG

    MODEL_NAMES: dict[str, str] = {
        "claude": "claude-sonnet-4-20250514",
        "grok": "grok-3",
        "gemini": "gemini-2.5-flash",
        "perplexity": "sonar-pro",
        "gpt": "gpt-4o",
        "copilot": "gpt-4o-azure",
        "ollama": "qwen3:32b",
    }

    def __init__(
        self,
        claude_api_key: str,
        anthropic_base_url: str = "https://api.anthropic.com",
        xai_api_key: Optional[str] = None,
        google_api_key: Optional[str] = None,
        perplexity_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        copilot_api_key: Optional[str] = None,
        ollama_host: str = "localhost:11434",
        max_rounds: int = 3,
        consensus_threshold: float = 70.0,
        paperclip_client: Optional[object] = None,
    ) -> None:
        # Store keys as private backing attributes; access via properties so
        # callers always get the live env-var value if the arg was None/empty.
        self._claude_api_key = claude_api_key
        self.anthropic_base_url = anthropic_base_url
        self._xai_api_key = xai_api_key
        self._google_api_key = google_api_key
        self._perplexity_api_key = perplexity_api_key
        self._openai_api_key = openai_api_key
        self._copilot_api_key = copilot_api_key  # None = fall through to env
        self.ollama_host = ollama_host
        self.max_rounds = max_rounds
        self.consensus_threshold = consensus_threshold
        # Default per-request timeout (seconds). Override via NCL_API_TIMEOUT env var.
        self._api_timeout: float = float(os.environ.get("NCL_API_TIMEOUT", "30"))
        self.http_client = httpx.AsyncClient(timeout=self._api_timeout)
        self._paperclip = paperclip_client  # Injected from brain.py
        self._session_costs: dict[str, int] = {}  # session_id → total cents

        # Rate limiter — max 5 council sessions per 60-second window
        self._rate_limit_max: int = int(os.environ.get("NCL_COUNCIL_RATE_LIMIT", "5"))
        self._rate_limit_window: float = float(os.environ.get("NCL_COUNCIL_RATE_WINDOW", "60"))
        self._rate_limit_timestamps: deque[float] = deque()  # monotonic timestamps
        self._rate_limit_lock = asyncio.Lock()

        # Log council member API key availability at init
        _key_status = {
            "Claude": bool(self.claude_api_key),
            "Grok (xAI)": bool(self.xai_api_key),
            "Gemini (Google)": bool(self.google_api_key),
            "Perplexity": bool(self.perplexity_api_key),
            "GPT (OpenAI)": bool(self.openai_api_key),
            "Copilot": bool(self.copilot_api_key),
        }
        _active = [k for k, v in _key_status.items() if v]
        _missing = [k for k, v in _key_status.items() if not v]
        log.info(f"Council API keys: {len(_active)}/6 configured — active: {_active}")
        if _missing:
            log.warning(
                f"Council members without API keys (will fallback to Ollama): {_missing}. "
                f"Set keys in .env to enable paid API access."
            )

    # ------------------------------------------------------------------
    # API key properties — read from env at point of use so keys can be
    # rotated without restarting the process.  Constructor args are the
    # initial/cached value; env vars take precedence when set.
    # ------------------------------------------------------------------

    @property
    def claude_api_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "") or self._claude_api_key or ""

    @property
    def xai_api_key(self) -> Optional[str]:
        return os.environ.get("XAI_API_KEY") or self._xai_api_key or None

    @property
    def google_api_key(self) -> Optional[str]:
        return os.environ.get("GOOGLE_API_KEY") or self._google_api_key or None

    @property
    def perplexity_api_key(self) -> Optional[str]:
        return os.environ.get("PERPLEXITY_API_KEY") or self._perplexity_api_key or None

    @property
    def openai_api_key(self) -> Optional[str]:
        return os.environ.get("OPENAI_API_KEY") or self._openai_api_key or None

    @property
    def copilot_api_key(self) -> Optional[str]:
        return os.environ.get("GITHUB_COPILOT_API_KEY") or self._copilot_api_key or None

    # ------------------------------------------------------------------
    # Rate limiter helpers
    # ------------------------------------------------------------------

    async def _check_rate_limit(self) -> None:
        """
        Enforce max council sessions per sliding window.

        Raises RuntimeError if the rate limit is exceeded.
        """
        async with self._rate_limit_lock:
            now = time.monotonic()
            cutoff = now - self._rate_limit_window
            # Purge timestamps outside the window
            while self._rate_limit_timestamps and self._rate_limit_timestamps[0] < cutoff:
                self._rate_limit_timestamps.popleft()
            if len(self._rate_limit_timestamps) >= self._rate_limit_max:
                oldest = self._rate_limit_timestamps[0]
                wait_secs = self._rate_limit_window - (now - oldest)
                log.warning(
                    f"[council] Rate limit hit ({self._rate_limit_max} sessions / "
                    f"{self._rate_limit_window:.0f}s). Retry in {wait_secs:.1f}s."
                )
                raise RuntimeError(
                    f"Council rate limit exceeded: max {self._rate_limit_max} sessions "
                    f"per {self._rate_limit_window:.0f}s. Retry in {wait_secs:.1f}s."
                )
            self._rate_limit_timestamps.append(now)

    async def spawn_session(
        self,
        topic: str,
        prompt: str,
        members: Optional[list[CouncilMember]] = None,
        session_id: Optional[str] = None,
    ) -> CouncilSession:
        """Spawn a new council debate session with role assignments."""
        await self._check_rate_limit()

        if members is None:
            members = list(CouncilMember)

        # Assign roles
        role_assignments = {}
        for member in members:
            role = DEFAULT_ROLE_MAP.get(member, CouncilRole.CREATIVE)
            role_assignments[member.value] = role.value

        session = CouncilSession(
            session_id=session_id or str(uuid.uuid4()),
            topic=topic,
            chair="claude",
            members=members,
            role_assignments=role_assignments,
            prompt=prompt,
            status=CouncilStatus.DEBATING,
            protocol="delphi-mad",
        )
        log.info(
            f"[council:{session.session_id}] Spawned — topic='{topic}', "
            f"members={[m.value for m in members]}, protocol=delphi-mad"
        )
        return session

    async def run_debate(self, session: CouncilSession) -> CouncilSession:
        """
        Run the full Delphi-MAD debate protocol.

        Phase 1 — POSITION:    Parallel initial positions from all members
        Phase 2 — REBUTTAL:    Cross-examination with access to all Round 1 responses
        Phase 3 — CONVERGENCE: Final positions after seeing all rebuttals
        Phase 4 — SYNTHESIS:   Claude (chair) synthesizes + scores consensus
        """
        try:
            return await self._run_debate_inner(session)
        except Exception as e:
            log.error(f"[council:{session.session_id}] Debate FAILED with unhandled error: {e}")
            session.status = CouncilStatus.FAILED
            session.completed_at = datetime.now(timezone.utc)
            session.synthesis = f"Council debate FAILED: {type(e).__name__}: {e}"
            session.consensus_score = ConsensusScore(
                agreement_pct=0.0,
                confidence_weighted=0.0,
                threshold_met=False,
                reason=f"Session failed: {e}",
            )
            return session

    async def _run_debate_inner(self, session: CouncilSession) -> CouncilSession:
        """Inner implementation of the debate protocol."""
        session.status = CouncilStatus.DEBATING
        debaters = [m for m in session.members if m != CouncilMember.CLAUDE]

        # ===================================================================
        # PAPERCLIP — Create tracking issue for this council session
        # ===================================================================
        _pc_issue_id = await self._paperclip_create_session_issue(session)

        # ===================================================================
        # Round 1 — POSITION (parallel, all members including chair)
        # ===================================================================
        log.info(f"[council:{session.session_id}] Round 1: POSITION")
        r1 = DebateRound(round_number=1, round_type="position")

        tasks = []
        for member in session.members:
            role = CouncilRole(session.role_assignments.get(member.value, "creative"))
            prompt = _build_round_prompt(
                round_type="position",
                round_number=1,
                topic=session.topic,
                base_prompt=session.prompt,
                role=role,
                member_name=member.value,
            )
            tasks.append(self._get_member_response_safe(member, prompt, session.session_id))

        results = await asyncio.gather(*tasks)
        for member, response in zip(session.members, results):
            r1.responses[member.value] = response
            r1.scores[member.value] = self._extract_confidence(response)
            log.info(
                f"[council:{session.session_id}] R1 {member.value}: {len(response)} chars, confidence={r1.scores.get(member.value, 0)}"  # noqa: E501
            )

        session.rounds.append(r1)

        # ===================================================================
        # QUORUM CHECK — After Round 1, verify minimum functioning members
        # ===================================================================
        unavailable_count = sum(
            1
            for resp in r1.responses.values()
            if resp.startswith("[") and "unavailable" in resp.lower().split("]", 1)[0]
        )
        functioning_count = len(session.members) - unavailable_count

        if unavailable_count > 2:  # More than 2 unavailable means fewer than 4 functioning
            log.error(
                f"[council:{session.session_id}] QUORUM FAILURE — "
                f"{unavailable_count} members unavailable, only {functioning_count} functioning. "
                f"Minimum 4 required. Halting debate."
            )
            session.status = CouncilStatus.COMPLETE
            session.completed_at = datetime.now(timezone.utc)
            session.synthesis = (
                f"Council debate HALTED due to insufficient quorum. "
                f"Unavailable members: {unavailable_count} / {len(session.members)}. "
                f"Minimum 4 functioning members required. Round 1 responses preserved for manual review."  # noqa: E501
            )
            session.consensus_score = ConsensusScore(
                agreement_pct=0.0,
                confidence_weighted=0.0,
                threshold_met=False,
                reason="Quorum not met",
            )
            await self._paperclip_report_quorum_failure(session, _pc_issue_id, unavailable_count)
            return session

        # PAPERCLIP — Report Round 1 costs
        await self._paperclip_report_round_costs(
            session.session_id,
            _pc_issue_id,
            1,
            [m.value for m in session.members],
        )

        # Brief delay between rounds to avoid rate-limit pressure on APIs
        await asyncio.sleep(0.5)

        # ===================================================================
        # Round 2 — REBUTTAL (parallel, debaters respond to all R1 positions)
        # ===================================================================
        log.info(f"[council:{session.session_id}] Round 2: REBUTTAL")
        r2 = DebateRound(round_number=2, round_type="rebuttal")

        tasks = []
        for member in debaters:
            role = CouncilRole(session.role_assignments.get(member.value, "creative"))
            prompt = _build_round_prompt(
                round_type="rebuttal",
                round_number=2,
                topic=session.topic,
                base_prompt=session.prompt,
                role=role,
                member_name=member.value,
                previous_responses=r1.responses,
            )
            tasks.append(self._get_member_response_safe(member, prompt, session.session_id))

        results = await asyncio.gather(*tasks)
        for member, response in zip(debaters, results):
            r2.responses[member.value] = response
            r2.scores[member.value] = self._extract_confidence(response)
            log.info(
                f"[council:{session.session_id}] R2 {member.value}: {len(response)} chars, confidence={r2.scores.get(member.value, 0)}"  # noqa: E501
            )

        session.rounds.append(r2)

        # ===================================================================
        # QUORUM CHECK — After Round 2, verify minimum functioning members
        # ===================================================================
        unavailable_count = sum(
            1
            for resp in r2.responses.values()
            if resp.startswith("[") and "unavailable" in resp.lower().split("]", 1)[0]
        )
        functioning_count = len(debaters) - unavailable_count

        if unavailable_count > 2:  # More than 2 unavailable among debaters
            log.error(
                f"[council:{session.session_id}] QUORUM FAILURE at Round 2 — "
                f"{unavailable_count} debaters unavailable, only {functioning_count} functioning. "
                f"Minimum 4 required. Halting debate."
            )
            session.status = CouncilStatus.COMPLETE
            session.completed_at = datetime.now(timezone.utc)
            session.synthesis = (
                f"Council debate HALTED due to insufficient quorum at Round 2. "
                f"Unavailable debaters: {unavailable_count} / {len(debaters)}. "
                f"Minimum 4 functioning members required. Rounds 1-2 responses preserved for manual review."  # noqa: E501
            )
            session.consensus_score = ConsensusScore(
                agreement_pct=0.0,
                confidence_weighted=0.0,
                threshold_met=False,
                reason="Quorum not met at Round 2",
            )
            await self._paperclip_report_quorum_failure(session, _pc_issue_id, unavailable_count)
            return session

        # PAPERCLIP — Report Round 2 costs
        await self._paperclip_report_round_costs(
            session.session_id,
            _pc_issue_id,
            2,
            [m.value for m in debaters],
        )

        # Brief delay between rounds to avoid rate-limit pressure on APIs
        await asyncio.sleep(0.5)

        # ===================================================================
        # Round 3 — CONVERGENCE (parallel, final positions)
        # ===================================================================
        log.info(f"[council:{session.session_id}] Round 3: CONVERGENCE")
        r3 = DebateRound(round_number=3, round_type="convergence")

        tasks = []
        for member in debaters:
            role = CouncilRole(session.role_assignments.get(member.value, "creative"))
            prompt = _build_round_prompt(
                round_type="convergence",
                round_number=3,
                topic=session.topic,
                base_prompt=session.prompt,
                role=role,
                member_name=member.value,
                round_history=session.rounds,
            )
            tasks.append(self._get_member_response_safe(member, prompt, session.session_id))

        results = await asyncio.gather(*tasks)
        for member, response in zip(debaters, results):
            r3.responses[member.value] = response
            r3.scores[member.value] = self._extract_confidence(response)
            session.responses[member.value] = response  # Final positions
            log.info(
                f"[council:{session.session_id}] R3 {member.value}: {len(response)} chars, confidence={r3.scores.get(member.value, 0)}"  # noqa: E501
            )

        session.rounds.append(r3)

        # PAPERCLIP — Report Round 3 costs
        await self._paperclip_report_round_costs(
            session.session_id,
            _pc_issue_id,
            3,
            [m.value for m in debaters],
        )

        # Brief delay before synthesis to avoid rate-limit pressure on APIs
        await asyncio.sleep(0.5)

        # ===================================================================
        # SYNTHESIS — Claude (chair) synthesizes all 3 rounds
        # ===================================================================
        log.info(f"[council:{session.session_id}] SYNTHESIS phase")
        session.status = CouncilStatus.SYNTHESIZING

        try:
            synthesis = await self._chair_synthesize(session)
            session.synthesis = synthesis
        except Exception as e:
            log.error(f"[council:{session.session_id}] Synthesis failed: {e}")
            session.synthesis = "Synthesis error — raw round data preserved for manual review."

        # ===================================================================
        # CONSENSUS SCORING — Quantify agreement
        # ===================================================================
        session.consensus_score = self._score_consensus(session)
        session.consensus, session.recommendations, session.dissents = self._extract_insights(
            session
        )

        # ===================================================================
        # PAPERCLIP — Post-synthesis lifecycle events
        # ===================================================================
        # Report synthesis cost (one more Claude call)
        await self._paperclip_report_round_costs(
            session.session_id,
            _pc_issue_id,
            4,  # Round 4 = synthesis
            ["claude"],
        )

        # Update issue with consensus results + cost totals
        await self._paperclip_update_synthesis(session, _pc_issue_id)

        # If consensus below threshold → request NATRIX approval before mandates
        if not session.consensus_score.threshold_met:
            await self._paperclip_request_low_consensus_review(session, _pc_issue_id)

        session.status = CouncilStatus.COMPLETE
        session.completed_at = datetime.now(timezone.utc)

        log.info(
            f"[council:{session.session_id}] COMPLETE — "
            f"consensus={session.consensus_score.agreement_pct:.0f}%, "
            f"threshold_met={session.consensus_score.threshold_met}, "
            f"recommendations={len(session.recommendations)}, "
            f"dissents={len(session.dissents)}, "
            f"total_cost={self._session_costs.get(session.session_id, 0)}¢"
        )

        return session

    # -----------------------------------------------------------------------
    # Member Response Dispatch (with fallback)
    # -----------------------------------------------------------------------

    async def _get_member_response_safe(
        self, member: CouncilMember, prompt: str, session_id: str
    ) -> str:
        """Get response with API fallback to Ollama."""
        try:
            return await self._get_member_response(member, prompt)
        except Exception as e:
            log.warning(
                f"[council:{session_id}] {member.value} API failed: {type(e).__name__}: {e!r}, trying Ollama"  # noqa: E501
            )
            try:
                return await self._get_ollama_response(member, prompt)
            except Exception as e2:
                log.error(
                    f"[council:{session_id}] {member.value} Ollama also failed: {type(e2).__name__}: {e2!r}"  # noqa: E501
                )
                return f"[{member.value} unavailable — both API and Ollama failed]"

    async def _get_member_response(self, member: CouncilMember, prompt: str) -> str:
        if member == CouncilMember.CLAUDE:
            return await self._call_claude(prompt)
        elif member == CouncilMember.GROK:
            return await self._call_grok(prompt)
        elif member == CouncilMember.GEMINI:
            return await self._call_gemini(prompt)
        elif member == CouncilMember.PERPLEXITY:
            return await self._call_perplexity(prompt)
        elif member == CouncilMember.GPT:
            return await self._call_gpt(prompt)
        elif member == CouncilMember.COPILOT:
            return await self._call_copilot(prompt)
        else:
            raise ValueError(f"Unknown member: {member}")

    # -----------------------------------------------------------------------
    # API Implementations
    # -----------------------------------------------------------------------

    async def _call_claude(
        self,
        prompt: str,
        documents: Optional[list[dict]] = None,
        return_response: bool = False,
    ):
        """Call Anthropic messages API via the runtime.llm facade.

        Return-shape contract (W4-06 tuple-semantics, preserved by W6-D):
        -----------------------------------------------------------------
        - When ``documents`` is non-empty: ALWAYS returns
          ``(text, response_json)`` — the tuple is implied by the
          Citations-API shape and is needed by ``parse_citations``.
          The legacy ``return_response`` flag is IGNORED in this branch
          (kept in the signature only for back-compat with any kwarg
          callers).
        - When ``documents`` is None/empty: returns ``text`` (str) —
          this is the back-compat hot path used by every member-response
          dispatch site (4 rounds x 5 members).

        W6-D migration note
        -------------------
        Transport was inline httpx → ``runtime.llm.chat``. The facade
        owns:
            * budget gate (anthropic key)
            * per-provider circuit breaker
            * retry-with-jitter (3 attempts; fatal HTTP 401/403/404 short-circuit)
            * Citations API passthrough (documents → first user message)
            * defensive response validation
            * cost recording

        The pre-call ``check_budget("anthropic", 0.25)`` was retained as a
        belt-and-suspenders guard because the chair-synthesis call is the
        most expensive single Anthropic call we make and we still want the
        explicit ``RuntimeError`` on a known-exhausted day rather than
        the facade's ``BudgetExhausted``. The facade does its own gate too
        with a more accurate ``estimate_cost`` so the second check is the
        binding one.

        Parameters
        ----------
        prompt : str
            Free-text directive / question. Always required.
        documents : list[dict], optional
            Anthropic Citations API document blocks
            (see runtime/council_pack/citations.py:build_citation_documents).
            When non-empty, the facade is given a single user message whose
            ``content`` is a list with the documents PREPENDED to the
            user-text block, enabling per-claim citation annotations.
            When None/empty, falls through to the legacy bare-string
            ``content`` path and returns just ``text``.
        return_response : bool, default False
            DEPRECATED. Retained only so existing keyword callers
            (``return_response=True``) don't raise TypeError. Tuple-vs-str
            return shape is now decided strictly by whether ``documents``
            is non-empty.
        """
        api_key = self.claude_api_key
        if not api_key:
            raise ValueError("Anthropic API key not configured")

        from ..cost_tracker import check_budget

        if not await check_budget("anthropic", 0.25):
            raise RuntimeError("Anthropic daily budget exceeded — council call blocked")

        # Build messages payload exactly as the facade expects.
        # When documents are present we hand the facade a single user
        # message whose `content` is already the full block list
        # ([doc1, doc2, ..., {"type":"text","text":prompt}]). The facade
        # will pass this through to Anthropic verbatim (see
        # _build_anthropic_user_content: list content on the first user
        # turn is extended, not re-wrapped).
        if documents:
            user_content: Any = [*documents, {"type": "text", "text": prompt}]
        else:
            user_content = prompt

        from ..llm import chat as _llm_chat
        from ..llm.errors import BudgetExhausted, FatalAPIError, RateLimited

        try:
            result = await _llm_chat(
                model="claude-sonnet-4-20250514",
                messages=[{"role": "user", "content": user_content}],
                max_tokens=2048,
                temperature=0.7,
                documents=documents,
                budget_key="anthropic",
                timeout_s=self._api_timeout,
            )
        except BudgetExhausted as exc:
            # Surface as RuntimeError so the legacy "Anthropic budget
            # exceeded" callers stay on the same except branch.
            raise RuntimeError(
                f"Anthropic daily budget exceeded — council call blocked ({exc})"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Claude API timed out after {self._api_timeout}s") from exc
        except FatalAPIError as exc:
            raise RuntimeError(f"Claude API HTTP {exc.status}") from exc
        except RateLimited as exc:
            raise RuntimeError(f"Claude API rate-limited: {exc}") from exc
        except httpx.TimeoutException as exc:
            # Defensive — facade should translate to asyncio.TimeoutError
            # but we keep this so the legacy except branch still catches.
            raise TimeoutError(f"Claude API timed out after {self._api_timeout}s") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Claude API HTTP {exc.response.status_code}") from exc

        text = result.text
        if not text:
            # The facade's validator already guards against missing
            # `content` keys; reaching this branch means the model
            # returned a non-text reply (tool_use / thinking only).
            raise ValueError("Claude returned no text content")

        # Return-shape is driven by `documents`, not `return_response`
        # (see docstring). `return_response` is kept only as an accepted
        # kwarg for back-compat; it has no effect on the chosen branch.
        if documents:
            return text, result.raw
        return text

    async def _call_grok(self, prompt: str) -> str:
        """Thin wrapper over the LLM facade. Provider gates (budget, breaker,
        retry, cost record) live in ``runtime.llm.chat``.
        """
        if not self.xai_api_key:
            raise ValueError("xAI API key not configured")
        return await self._llm_facade_call(
            model="grok-3",
            prompt=prompt,
            budget_key="xai",
            temperature=0.8,
            provider_label="Grok",
        )

    async def _call_gemini(self, prompt: str) -> str:
        """Thin wrapper over the LLM facade. See ``_call_grok`` docstring."""
        if not self.google_api_key:
            raise ValueError("Google API key not configured")
        return await self._llm_facade_call(
            model="gemini-2.5-flash",
            prompt=prompt,
            budget_key="google",
            temperature=0.7,
            provider_label="Gemini",
        )

    async def _call_perplexity(self, prompt: str) -> str:
        """Thin wrapper over the LLM facade. See ``_call_grok`` docstring."""
        if not self.perplexity_api_key:
            raise ValueError("Perplexity API key not configured")
        return await self._llm_facade_call(
            model="sonar-pro",
            prompt=prompt,
            budget_key="perplexity",
            temperature=0.5,
            provider_label="Perplexity",
        )

    async def _call_gpt(self, prompt: str) -> str:
        """Thin wrapper over the LLM facade. See ``_call_grok`` docstring."""
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not configured")
        return await self._llm_facade_call(
            model="gpt-4o",
            prompt=prompt,
            budget_key="openai",
            temperature=0.9,
            provider_label="GPT",
        )

    async def _llm_facade_call(
        self,
        *,
        model: str,
        prompt: str,
        budget_key: str,
        temperature: float,
        provider_label: str,
        system: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        """Shared façade-call helper for non-Anthropic council members.

        Translates the facade's structured errors into the legacy
        ``TimeoutError`` / ``RuntimeError`` / ``ValueError`` shapes that
        ``_get_member_response`` and the Ollama fallback path expect.
        """
        from ..llm import chat as _llm_chat
        from ..llm.errors import (
            BudgetExhausted,
            CircuitOpen,
            FatalAPIError,
            LLMError,
            RateLimited,
        )

        try:
            result = await _llm_chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                budget_key=budget_key,
                timeout_s=self._api_timeout,
            )
        except BudgetExhausted as exc:
            raise RuntimeError(
                f"{provider_label} daily budget exceeded — council call blocked ({exc})"
            ) from exc
        except CircuitOpen as exc:
            raise RuntimeError(f"{provider_label} circuit open: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"{provider_label} API timed out after {self._api_timeout}s"
            ) from exc
        except FatalAPIError as exc:
            raise RuntimeError(f"{provider_label} API HTTP {exc.status}") from exc
        except RateLimited as exc:
            raise RuntimeError(f"{provider_label} API rate-limited: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"{provider_label} API timed out after {self._api_timeout}s"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"{provider_label} API HTTP {exc.response.status_code}") from exc
        except LLMError as exc:
            raise RuntimeError(f"{provider_label} API error: {exc}") from exc

        text = result.text or ""
        if not text:
            raise ValueError(f"{provider_label} returned no text content")
        return text

    async def _call_copilot(self, prompt: str) -> str:
        """
        Call Microsoft Azure OpenAI for the ENGINEER council role.

        Priority chain:
        1. Azure OpenAI (M365 enterprise — AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_KEY)
        2. GitHub Copilot key (GITHUB_COPILOT_API_KEY)
        3. OpenAI fallback (shared key, engineering system prompt)
        4. Ollama deepseek-coder-v2:16b (local)
        """
        # Try Azure OpenAI first (M365 enterprise path)
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        azure_key = os.getenv("AZURE_OPENAI_KEY", "")
        azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

        if azure_endpoint and azure_key:
            url = (
                f"{azure_endpoint.rstrip('/')}/openai/deployments/{azure_deployment}"
                f"/chat/completions?api-version={azure_api_version}"
            )
            try:
                resp = await self.http_client.post(
                    url,
                    headers={
                        "api-key": azure_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "messages": [
                            {
                                "role": "system",
                                "content": ROLE_SYSTEM_PROMPTS[CouncilRole.ENGINEER],
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.5,
                        "max_tokens": 2048,
                    },
                    timeout=self._api_timeout,
                )
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"Azure OpenAI timed out after {self._api_timeout}s") from exc
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Azure OpenAI HTTP {exc.response.status_code}") from exc
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                # Track Azure cost
                try:
                    from ..cost_tracker import record_cost

                    usage = data.get("usage", {})
                    input_t = usage.get("prompt_tokens", 0)
                    output_t = usage.get("completion_tokens", 0)
                    cost = (input_t * 2.5 + output_t * 10.0) / 1_000_000
                    await record_cost(
                        "openai",
                        cost,
                        "council_run",
                        f"azure-{azure_deployment} in={input_t} out={output_t}",
                        model=azure_deployment,
                        input_tokens=input_t,
                        output_tokens=output_t,
                    )
                except Exception:
                    pass
                return choices[0].get("message", {}).get("content", "")

        # Fallback: OpenAI direct via the LLM facade.
        #
        # Azure OpenAI (above) stays on the raw httpx path because the
        # facade has no Azure endpoint shape (custom URL per deployment,
        # ``api-key`` header instead of ``Authorization: Bearer``). When
        # AZURE_OPENAI_* is unset we drop to the OpenAI shape, which the
        # facade owns end-to-end (budget + breaker + retry + cost record).
        if not (self.copilot_api_key or self.openai_api_key):
            raise ValueError("No Azure, Copilot, or OpenAI API key configured for ENGINEER role")
        return await self._llm_facade_call(
            model="gpt-4o",
            prompt=prompt,
            budget_key="openai",
            temperature=0.5,
            provider_label="Copilot/OpenAI",
            system=ROLE_SYSTEM_PROMPTS[CouncilRole.ENGINEER],
            max_tokens=2048,
        )

    async def _get_ollama_response(self, member: CouncilMember, prompt: str) -> str:
        """Fallback to local Ollama model.

        Uses qwen3:8b for all members — faster (3-5s) than qwen3:32b under
        parallel load. Ollama serializes calls per model, so heavier weights
        cause cascading timeouts when 4+ members fan out simultaneously.
        """
        model_map = {
            CouncilMember.CLAUDE: "qwen3:8b",
            CouncilMember.GROK: "qwen3:8b",
            CouncilMember.GEMINI: "qwen3:8b",
            CouncilMember.PERPLEXITY: "qwen3:8b",
            CouncilMember.GPT: "qwen3:8b",
            CouncilMember.COPILOT: "deepseek-coder-v2:16b",
        }
        model = model_map.get(member, "qwen3:8b")

        # Per-call timeout override — first cold load can take ~30s,
        # then queued parallel calls add up. 240s gives headroom.
        resp = await self.http_client.post(
            f"http://{self.ollama_host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=240.0,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    # -----------------------------------------------------------------------
    # Chair Synthesis — Claude moderates and produces final output
    # -----------------------------------------------------------------------

    async def _chair_synthesize(self, session: CouncilSession) -> str:
        """Claude (chair) synthesizes all rounds into final output."""

        # Build comprehensive debate transcript for chair
        transcript = f"TOPIC: {session.topic}\nPROTOCOL: Delphi-MAD (3-round)\n\n"

        for rnd in session.rounds:
            transcript += f"=== ROUND {rnd.round_number}: {rnd.round_type.upper()} ===\n"
            for member_name, response in rnd.responses.items():
                role = session.role_assignments.get(member_name, "member")
                conf = rnd.scores.get(member_name, 0)
                transcript += f"\n[{member_name.upper()} ({role})] confidence={conf}:\n"
                transcript += response[:800] + ("\n..." if len(response) > 800 else "\n")
            transcript += "\n"

        synthesis_prompt = (
            f"{ROLE_SYSTEM_PROMPTS[CouncilRole.CHAIR]}\n\n"
            f"COUNCIL DEBATE TRANSCRIPT:\n{transcript}\n\n"
            f"As CHAIR, produce the FINAL SYNTHESIS as a JSON object with this exact structure:\n\n"
            f'{{"consensus": "the consensus position",'
            f' "agreement_pct": 75,'
            f' "key_insights": ["insight 1", "insight 2", "insight 3"],'
            f' "dissents": ["dissent 1"],'
            f' "mandate_recommendations": ['
            f'{{"pillar": "NCL", "title": "mandate title", "objective": "objective", "priority": 5, "success_criteria": ["criteria 1"]}}],'  # noqa: E501
            f' "risk_flags": ["risk 1"],'
            f' "confidence": 80}}\n\n'
            f"Respond with ONLY the JSON object, no markdown fences. "
            f"Be decisive. NATRIX needs clear direction, not hedge-everything caution."
        )

        # If session has Anthropic Citations document blocks attached (set by
        # council_pack.runners.run_council_with_pack), use the dual-shape call
        # that returns (text, response_json) so we can parse citation
        # annotations downstream. Otherwise stay on the legacy string-only
        # path (back-compat with every non-pack caller).
        session_documents = getattr(session, "documents", None) or []
        try:
            if session_documents:
                raw, response_json = await self._call_claude(
                    synthesis_prompt,
                    documents=session_documents,
                )
                # Stash for parse_citations() in the runner. Success path.
                try:
                    session.synthesis_response_json = response_json
                except Exception:
                    pass
            else:
                raw = await self._call_claude(synthesis_prompt)
                # No documents attached -> there can never be Citations to
                # parse downstream. Make this explicit so the runner can
                # distinguish "no documents" from "API call failed".
                try:
                    session.synthesis_response_json = None
                except Exception:
                    pass
        except Exception as e:
            log.warning(
                f"[council:{session.session_id}] chair synthesis API failed: "
                f"{type(e).__name__}: {e!r}, falling back to Ollama"
            )
            # Fallback path -> Ollama doesn't speak Citations. Explicitly
            # stamp None so the runner reports `citations_status =
            # "fallback_no_citations"` rather than silently dropping the
            # Citations grounding the caller asked for.
            try:
                session.synthesis_response_json = None
            except Exception:
                pass
            if session_documents:
                log.info(
                    f"[council:{session.session_id}] [chair] synthesis used "
                    f"fallback; citations dropped"
                )
            raw = await self._get_ollama_response(CouncilMember.CLAUDE, synthesis_prompt)

        # Try to parse JSON response; fall back to raw text if parsing fails
        try:
            # Strip markdown fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[1:])
            if cleaned.endswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[:-1])
            cleaned = cleaned.strip()
            parsed = json.loads(cleaned)
            # Reformat as structured text for downstream compatibility
            structured = f"CONSENSUS: {parsed.get('consensus', '')}\n"
            structured += f"AGREEMENT_PERCENTAGE: {parsed.get('agreement_pct', 0)}\n"
            structured += f"CONFIDENCE: {parsed.get('confidence', 0)}\n\n"
            structured += "KEY_INSIGHTS:\n"
            for insight in parsed.get("key_insights", []):
                structured += f"- {insight}\n"
            structured += "\nDISSENTS:\n"
            for d in parsed.get("dissents", []):
                structured += f"- {d}\n"
            structured += "\nMANDATE_RECOMMENDATIONS:\n"
            for m in parsed.get("mandate_recommendations", []):
                structured += f"- PILLAR: {m.get('pillar', '?')}\n"
                structured += f"  TITLE: {m.get('title', '?')}\n"
                structured += f"  OBJECTIVE: {m.get('objective', '?')}\n"
                structured += f"  PRIORITY: {m.get('priority', 5)}\n"
                structured += f"  SUCCESS_CRITERIA: {', '.join(m.get('success_criteria', []))}\n"
            structured += "\nRISK_FLAGS:\n"
            for r in parsed.get("risk_flags", []):
                structured += f"- {r}\n"
            return structured
        except (json.JSONDecodeError, TypeError, KeyError):
            # JSON parsing failed — return raw text for regex fallback extraction
            log.warning("Council synthesis JSON parse failed, using raw text fallback")
            return raw

    # -----------------------------------------------------------------------
    # Consensus Scoring Engine
    # -----------------------------------------------------------------------

    def _score_consensus(self, session: CouncilSession) -> ConsensusScore:
        """
        Quantify consensus across council members.

        Uses agreement detection from Round 3 (convergence) responses
        and confidence weighting from all rounds.
        """
        score = ConsensusScore()

        if not session.rounds:
            return score

        # Get Round 3 (convergence) data
        r3 = next(
            (r for r in reversed(session.rounds) if r.round_type == "convergence"),
            None,
        )
        if r3 is None:
            # No convergence round — score is inconclusive, do not fall back to wrong data
            score.agreement_pct = 0.0
            score.confidence_weighted = 0.0
            score.threshold_met = False
            score.unanimous = False
            score.dissent_strength = 0.0
            log.warning(
                "[council] _score_consensus: no convergence round found for session %s — "
                "returning inconclusive score",
                session.session_id,
            )
            return score

        confidences = list(r3.scores.values()) if r3 else []
        if not confidences:
            return score

        # Average confidence across members
        avg_confidence = sum(confidences) / len(confidences)

        # Agreement detection: count AGREE vs DISAGREE in Round 3 responses
        agree_count = 0
        disagree_count = 0
        total_members = len(r3.responses) if r3 else 0

        for member_name, response in (r3.responses if r3 else {}).items():
            lower = response.lower()
            # Count agreement signals
            agree_signals = len(
                re.findall(
                    r"\bagree\b|\bconsensus\b|\balign\b|\bsupport\b|\bconcur\b|\bendorse\b", lower
                )
            )
            disagree_signals = len(
                re.findall(
                    r"\bdisagree\b|\bdissent\b|\boppose\b|\breject\b|\bchallenge\b|\bcontra\b",
                    lower,
                )
            )

            if agree_signals > disagree_signals:
                agree_count += 1
            elif disagree_signals > agree_signals:
                disagree_count += 1
            else:
                agree_count += 0.5  # Neutral counts as partial agreement

        # Calculate scores
        if total_members > 0:
            score.agreement_pct = (agree_count / total_members) * 100
        score.confidence_weighted = avg_confidence * (score.agreement_pct / 100)
        score.unanimous = int(agree_count) >= total_members and disagree_count == 0
        score.threshold_met = score.agreement_pct >= self.consensus_threshold
        score.dissent_strength = (disagree_count / max(total_members, 1)) * 100

        # Convergence delta: how much positions shifted from R1 to R3
        # Only compare members present in both rounds (handles dropouts).
        if len(session.rounds) >= 3:
            r1_scores = session.rounds[0].scores
            r3_scores = session.rounds[2].scores
            common_members = set(r1_scores.keys()) & set(r3_scores.keys())
            if common_members:
                r1_confs = [r1_scores[m] for m in common_members]
                r3_confs = [r3_scores[m] for m in common_members]
                r1_spread = max(r1_confs) - min(r1_confs)
                r3_spread = max(r3_confs) - min(r3_confs)
                score.convergence_delta = r1_spread - r3_spread  # Positive = converged

        return score

    # -----------------------------------------------------------------------
    # Insight Extraction
    # -----------------------------------------------------------------------

    def _extract_insights(
        self, session: CouncilSession
    ) -> tuple[Optional[str], list[str], list[str]]:
        """Extract consensus, recommendations, and dissents from synthesis."""
        synthesis = session.synthesis or ""
        if not synthesis:
            return "No synthesis available.", [], []

        consensus = None
        recommendations: list[str] = []
        dissents: list[str] = []

        lines = synthesis.split("\n")
        current_section = None

        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()

            # Detect section headers
            if any(
                kw in lower
                for kw in ["consensus:", "consensus position", "agreement", "common ground"]
            ):
                current_section = "consensus"
                # Check if the content is on the same line after ':'
                after_colon = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                if after_colon and len(after_colon) > 10:
                    consensus = after_colon
                continue
            elif any(
                kw in lower
                for kw in [
                    "mandate_recommendation",
                    "recommendation",
                    "action item",
                    "next step",
                    "mandate",
                ]
            ):
                current_section = "recommendations"
                continue
            elif any(kw in lower for kw in ["dissent", "disagreement", "minority", "unresolved"]):
                current_section = "dissents"
                continue
            elif any(kw in lower for kw in ["risk_flag", "risk", "warning", "critical risk"]):
                current_section = "risks"
                continue
            elif any(kw in lower for kw in ["key_insight", "insight", "strategic insight"]):
                current_section = "insights"
                continue

            # Extract content based on section
            if stripped and current_section:
                clean = re.sub(r"^[\d\.\-\*\+]+\s*", "", stripped)
                if clean and len(clean) > 5:
                    if current_section == "consensus" and not consensus:
                        consensus = clean
                    elif current_section == "consensus" and consensus:
                        consensus += " " + clean
                    elif current_section == "recommendations":
                        recommendations.append(clean)
                    elif current_section == "dissents":
                        dissents.append(clean)
                    elif current_section == "risks":
                        dissents.append(f"[RISK] {clean}")
                    elif current_section == "insights":
                        recommendations.append(f"[INSIGHT] {clean}")

        # Fallback parsing
        if not consensus:
            paragraphs = [p.strip() for p in synthesis.split("\n\n") if p.strip()]
            consensus = (
                paragraphs[0]
                if paragraphs
                else "Synthesis produced but no clear consensus extracted."
            )

        if not recommendations:
            for line in lines:
                stripped = line.strip()
                if any(
                    kw in stripped.lower()
                    for kw in ["should", "recommend", "suggest", "prioritize", "pillar:"]
                ):
                    clean = re.sub(r"^[\d\.\-\*\+]+\s*", "", stripped)
                    if clean and len(clean) > 10:
                        recommendations.append(clean)

        return consensus, recommendations[:15], dissents[:10]

    @staticmethod
    def _extract_confidence(response: str) -> float:
        """Extract confidence score from a member's response."""
        match = re.search(r"(?:CONFIDENCE|confidence)\s*[:=]\s*(\d+)", response)
        if match:
            return min(100.0, max(0.0, float(match.group(1))))
        # Heuristic: count certainty language
        lower = response.lower()
        certainty_words = len(
            re.findall(r"\bcertain\b|\bconfident\b|\bclearly\b|\bdefinitely\b|\bstrongly\b", lower)
        )
        uncertainty_words = len(
            re.findall(
                r"\buncertain\b|\bperhaps\b|\bmaybe\b|\bpossibly\b|\bmight\b|\bunsure\b", lower
            )
        )
        base = 50.0
        base += certainty_words * 8
        base -= uncertainty_words * 8
        return max(10.0, min(90.0, base))

    # -----------------------------------------------------------------------
    # Paperclip Integration — Council Lifecycle Tracking
    # -----------------------------------------------------------------------

    async def _paperclip_create_session_issue(self, session: CouncilSession) -> str | None:
        """Create a Paperclip issue to track the council session lifecycle."""
        if not self._paperclip:
            return None
        try:
            paperclip_url = os.getenv("PAPERCLIP_URL", "http://localhost:3100")
            company_id = os.getenv("PAPERCLIP_COMPANY_ID", "")
            if not company_id:
                log.warning(
                    "[council:paperclip] No PAPERCLIP_COMPANY_ID set, skipping issue creation"
                )
                return None

            # Actual Paperclip createIssueSchema: title, description, status, priority
            resp = await self.http_client.post(
                f"{paperclip_url}/api/companies/{company_id}/issues",
                json={
                    "title": f"Council: {session.topic[:80]}",
                    "description": (
                        f"[council-session] {session.session_id}\n"
                        f"Protocol: {session.protocol}\n"
                        f"Members: {', '.join(m.value for m in session.members)}\n"
                        f"Roles: {session.role_assignments}\n"
                        f"Prompt: {session.prompt[:500]}"
                    ),
                    "status": "in_progress",
                    "priority": "urgent",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            issue_id = resp.json().get("id", resp.json().get("issue_id"))
            log.info(
                f"[council:paperclip] Created issue {issue_id} for session {session.session_id}"
            )
            return issue_id
        except Exception as e:
            log.warning(f"[council:paperclip] Failed to create session issue: {e}")
            return None

    async def _paperclip_report_round_costs(
        self, session_id: str, issue_id: str | None, round_num: int, members: list[str]
    ) -> None:
        """Report API costs for a completed debate round to Paperclip."""
        if not self._paperclip:
            return
        try:
            paperclip_url = os.getenv("PAPERCLIP_URL", "http://localhost:3100")
            company_id = os.getenv("PAPERCLIP_COMPANY_ID", "")
            if not company_id:
                return
            total_round_cost = 0

            for member_name in members:
                cost_cents = self.COST_ESTIMATES_CENTS.get(member_name, 3)
                model = self.MODEL_NAMES.get(member_name, "unknown")
                total_round_cost += cost_cents

                # Actual Paperclip endpoint: POST /api/companies/:companyId/cost-events
                await self.http_client.post(
                    f"{paperclip_url}/api/companies/{company_id}/cost-events",
                    json={
                        "agentId": f"council-{member_name}",
                        "model": model,
                        "costCents": cost_cents,
                        "occurredAt": datetime.now(timezone.utc).isoformat(),
                    },
                    timeout=5.0,
                )

            # Update running total
            self._session_costs[session_id] = (
                self._session_costs.get(session_id, 0) + total_round_cost
            )
            log.info(
                f"[council:paperclip] Round {round_num} costs reported: "
                f"{total_round_cost}¢ ({len(members)} members), "
                f"session total: {self._session_costs[session_id]}¢"
            )
        except Exception as e:
            log.warning(f"[council:paperclip] Cost reporting failed for round {round_num}: {e}")

    async def _paperclip_update_synthesis(
        self, session: CouncilSession, issue_id: str | None
    ) -> None:
        """Update Paperclip issue with synthesis results and consensus score."""
        if not self._paperclip or not issue_id:
            return
        try:
            paperclip_url = os.getenv("PAPERCLIP_URL", "http://localhost:3100")
            company_id = os.getenv("PAPERCLIP_COMPANY_ID", "")

            # Actual Paperclip endpoint: PATCH /api/issues/:id (NOT under /companies)
            await self.http_client.patch(
                f"{paperclip_url}/api/issues/{issue_id}",
                json={
                    "status": "done" if session.consensus_score.threshold_met else "todo",
                    "description": (
                        f"Council session {session.session_id}\n"
                        f"Consensus: {session.consensus_score.agreement_pct:.0f}%\n"
                        f"Threshold met: {session.consensus_score.threshold_met}\n"
                        f"Recommendations: {len(session.recommendations)}\n"
                        f"Dissents: {len(session.dissents)}\n"
                        f"Total cost: {self._session_costs.get(session.session_id, 0)}¢"
                    ),
                },
                timeout=10.0,
            )

            # Actual Paperclip endpoint: POST /api/companies/:companyId/activity
            await self.http_client.post(
                f"{paperclip_url}/api/companies/{company_id}/activity",
                json={
                    "actorType": "agent",
                    "actorId": "council-chair",
                    "action": "council.synthesis_complete",
                    "entityType": "issue",
                    "entityId": issue_id,
                    "details": {
                        "consensus_pct": session.consensus_score.agreement_pct,
                        "convergence_delta": session.consensus_score.convergence_delta,
                        "threshold_met": session.consensus_score.threshold_met,
                        "recommendations_count": len(session.recommendations),
                        "dissents_count": len(session.dissents),
                        "total_cost_cents": self._session_costs.get(session.session_id, 0),
                    },
                },
                timeout=10.0,
            )

            log.info(
                f"[council:paperclip] Synthesis updated on issue {issue_id}: "
                f"{session.consensus_score.agreement_pct:.0f}% consensus"
            )
        except Exception as e:
            log.warning(f"[council:paperclip] Synthesis update failed: {e}")

    async def _paperclip_request_low_consensus_review(
        self, session: CouncilSession, issue_id: str | None
    ) -> None:
        """Request NATRIX approval when consensus is below threshold."""
        if not self._paperclip or not issue_id:
            return
        try:
            paperclip_url = os.getenv("PAPERCLIP_URL", "http://localhost:3100")
            company_id = os.getenv("PAPERCLIP_COMPANY_ID", "")
            if not company_id:
                return

            # Actual Paperclip endpoint: POST /api/companies/:companyId/approvals
            await self.http_client.post(
                f"{paperclip_url}/api/companies/{company_id}/approvals",
                json={
                    "type": "low-consensus-review",
                    "payload": {
                        "issue_id": issue_id,
                        "session_id": session.session_id,
                        "topic": session.topic,
                        "consensus_pct": session.consensus_score.agreement_pct,
                        "threshold": self.consensus_threshold,
                        "dissent_strength": session.consensus_score.dissent_strength,
                        "dissents": session.dissents[:5],
                        "recommendations": session.recommendations[:5],
                        "reason": (
                            f"Council consensus at {session.consensus_score.agreement_pct:.0f}% "
                            f"(threshold: {self.consensus_threshold}%). "
                            f"NATRIX review required before mandate generation."
                        ),
                    },
                    "issueIds": [issue_id],
                },
                timeout=10.0,
            )

            log.warning(
                f"[council:paperclip] Low consensus ({session.consensus_score.agreement_pct:.0f}%) — "  # noqa: E501
                f"approval request sent to NATRIX for session {session.session_id}"
            )
        except Exception as e:
            log.warning(f"[council:paperclip] Approval request failed: {e}")

    async def _paperclip_report_quorum_failure(
        self, session: CouncilSession, issue_id: str | None, unavailable_count: int
    ) -> None:
        """Report council quorum failure to Paperclip."""
        if not self._paperclip or not issue_id:
            return
        try:
            paperclip_url = os.getenv("PAPERCLIP_URL", "http://localhost:3100")
            company_id = os.getenv("PAPERCLIP_COMPANY_ID", "")
            if not company_id:
                return

            # Report quorum failure to Paperclip
            await self.http_client.post(
                f"{paperclip_url}/api/companies/{company_id}/alerts",
                json={
                    "type": "council-quorum-failure",
                    "severity": "critical",
                    "payload": {
                        "issue_id": issue_id,
                        "session_id": session.session_id,
                        "topic": session.topic,
                        "unavailable_members": unavailable_count,
                        "total_members": len(session.members),
                        "functioning_members": len(session.members) - unavailable_count,
                        "reason": (
                            f"Council debate halted: {unavailable_count} members unavailable. "
                            f"Minimum 4 functioning members required."
                        ),
                    },
                    "issueIds": [issue_id],
                },
                timeout=10.0,
            )

            log.error(
                f"[council:paperclip] Quorum failure ({unavailable_count} unavailable) — "
                f"alert sent to Paperclip for session {session.session_id}"
            )
        except Exception as e:
            log.warning(f"[council:paperclip] Quorum failure alert failed: {e}")

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()
