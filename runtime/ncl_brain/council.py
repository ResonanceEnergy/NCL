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
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from .models import (
    CouncilSession,
    CouncilStatus,
    CouncilMember,
    CouncilRole,
    CouncilOutput,
    DebateRound,
    ConsensusScore,
)

log = logging.getLogger("ncl.council")

# ---------------------------------------------------------------------------
# Role Prompting System — Each member gets a unique persona + lens
# ---------------------------------------------------------------------------

ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    CouncilRole.CHAIR: (
        "You are the CHAIR of the Resonance Energy AI Council. You moderate debate, "
        "ensure all perspectives are heard, synthesize arguments into actionable consensus, "
        "and make final judgments when the council cannot agree. You are impartial but decisive. "
        "You identify the strongest arguments, flag weak reasoning, and produce clear mandates."
    ),
    CouncilRole.STRATEGIST: (
        "You are the STRATEGIST on the Resonance Energy AI Council. Your lens is bold, "
        "first-strike intuition. You think in terms of competitive advantage, speed-to-market, "
        "asymmetric bets, and opportunity cost. You challenge safe thinking and push for decisive "
        "action. You ask: 'What's the 10x move here?' and 'What are we missing that competitors "
        "will exploit?' You are contrarian when the group is too cautious."
    ),
    CouncilRole.ANALYST: (
        "You are the ANALYST on the Resonance Energy AI Council. Your lens is data-driven, "
        "structured analysis. You break problems into quantifiable components, assess risk with "
        "probabilities, and demand evidence for claims. You ask: 'What does the data show?' and "
        "'What are the measurable success criteria?' You flag when decisions are based on "
        "assumption rather than evidence. You provide structured frameworks."
    ),
    CouncilRole.RESEARCHER: (
        "You are the RESEARCHER on the Resonance Energy AI Council. Your lens is fact-checking, "
        "source verification, and real-time intelligence. You ground the discussion in what is "
        "actually true and currently happening in the market. You ask: 'What are the latest "
        "developments?' and 'Does this align with current market reality?' You flag claims that "
        "need verification and provide counter-evidence when available."
    ),
    CouncilRole.CREATIVE: (
        "You are the CREATIVE on the Resonance Energy AI Council. Your lens is lateral thinking, "
        "alternative approaches, and edge cases. You find solutions the group hasn't considered, "
        "challenge framing assumptions, and propose unconventional paths. You ask: 'What if we "
        "approached this completely differently?' and 'What are the second-order effects nobody "
        "is considering?' You are the voice of innovation and managed chaos."
    ),
    CouncilRole.ENGINEER: (
        "You are the ENGINEER on the Resonance Energy AI Council. Your lens is technical "
        "feasibility, implementation cost, and architectural soundness. You evaluate whether "
        "proposals can actually be built, how long they'll take, and what technical debt they'll "
        "create. You ask: 'Can we actually ship this?' and 'What's the simplest architecture "
        "that works?' You flag technically impossible proposals and suggest pragmatic alternatives. "
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
            f"Your initial position was:\n{previous_responses.get(member_name, '(no response)')[:400]}\n\n"
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
            f"This is the FINAL round. As the {role.value.upper()}, provide your definitive position.\n"
            f"Structure your response as:\n"
            f"FINAL_POSITION: Your definitive stance after hearing all arguments\n"
            f"AGREE_WITH: Which members/arguments you agree with and why\n"
            f"DISSENT: Any remaining disagreements (or 'None')\n"
            f"MANDATE: Your recommended mandate(s) with PILLAR, TITLE, OBJECTIVE, PRIORITY, SUCCESS_CRITERIA\n"
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

    # Estimated cost per API call in cents (for Paperclip cost tracking)
    COST_ESTIMATES_CENTS: dict[str, int] = {
        "claude": 5,       # ~1500 tokens in + 800 out on claude-sonnet-4-6
        "grok": 4,         # Grok-3 comparable
        "gemini": 1,       # Gemini Flash is cheap
        "perplexity": 3,   # Sonar Pro
        "gpt": 5,          # GPT-4o
        "copilot": 5,      # Azure/GPT-4o
        "ollama": 0,       # Local — free
    }

    MODEL_NAMES: dict[str, str] = {
        "claude": "claude-sonnet-4-6",
        "grok": "grok-3",
        "gemini": "gemini-2.0-flash",
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
        self.claude_api_key = claude_api_key
        self.anthropic_base_url = anthropic_base_url
        self.xai_api_key = xai_api_key
        self.google_api_key = google_api_key
        self.perplexity_api_key = perplexity_api_key
        self.openai_api_key = openai_api_key
        self.copilot_api_key = copilot_api_key or os.getenv("GITHUB_COPILOT_API_KEY", "")
        self.ollama_host = ollama_host
        self.max_rounds = max_rounds
        self.consensus_threshold = consensus_threshold
        self.http_client = httpx.AsyncClient(timeout=90.0)
        self._paperclip = paperclip_client  # Injected from brain.py
        self._session_costs: dict[str, int] = {}  # session_id → total cents

    async def spawn_session(
        self, topic: str, prompt: str, members: Optional[list[CouncilMember]] = None
    ) -> CouncilSession:
        """Spawn a new council debate session with role assignments."""
        if members is None:
            members = list(CouncilMember)

        # Assign roles
        role_assignments = {}
        for member in members:
            role = DEFAULT_ROLE_MAP.get(member, CouncilRole.CREATIVE)
            role_assignments[member.value] = role.value

        session = CouncilSession(
            session_id=str(uuid.uuid4()),
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
            log.info(f"[council:{session.session_id}] R1 {member.value}: {len(response)} chars, confidence={r1.scores.get(member.value, 0)}")

        session.rounds.append(r1)

        # ===================================================================
        # QUORUM CHECK — After Round 1, verify minimum functioning members
        # ===================================================================
        unavailable_count = sum(
            1 for resp in r1.responses.values()
            if "unavailable" in resp.lower() or "[" in resp and "]" in resp and "unavailable" in resp.lower()
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
                f"Minimum 4 functioning members required. Round 1 responses preserved for manual review."
            )
            session.consensus_score = ConsensusScore(
                agreement_pct=0.0,
                confidence=0.0,
                threshold_met=False,
                reason="Quorum not met"
            )
            await self._paperclip_report_quorum_failure(session, _pc_issue_id, unavailable_count)
            return session

        # PAPERCLIP — Report Round 1 costs
        await self._paperclip_report_round_costs(
            session.session_id, _pc_issue_id, 1,
            [m.value for m in session.members],
        )

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
            log.info(f"[council:{session.session_id}] R2 {member.value}: {len(response)} chars, confidence={r2.scores.get(member.value, 0)}")

        session.rounds.append(r2)

        # ===================================================================
        # QUORUM CHECK — After Round 2, verify minimum functioning members
        # ===================================================================
        unavailable_count = sum(
            1 for resp in r2.responses.values()
            if "unavailable" in resp.lower() or "[" in resp and "]" in resp and "unavailable" in resp.lower()
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
                f"Minimum 4 functioning members required. Rounds 1-2 responses preserved for manual review."
            )
            session.consensus_score = ConsensusScore(
                agreement_pct=0.0,
                confidence=0.0,
                threshold_met=False,
                reason="Quorum not met at Round 2"
            )
            await self._paperclip_report_quorum_failure(session, _pc_issue_id, unavailable_count)
            return session

        # PAPERCLIP — Report Round 2 costs
        await self._paperclip_report_round_costs(
            session.session_id, _pc_issue_id, 2,
            [m.value for m in debaters],
        )

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
            log.info(f"[council:{session.session_id}] R3 {member.value}: {len(response)} chars, confidence={r3.scores.get(member.value, 0)}")

        session.rounds.append(r3)

        # PAPERCLIP — Report Round 3 costs
        await self._paperclip_report_round_costs(
            session.session_id, _pc_issue_id, 3,
            [m.value for m in debaters],
        )

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
        session.consensus, session.recommendations, session.dissents = (
            self._extract_insights(session)
        )

        # ===================================================================
        # PAPERCLIP — Post-synthesis lifecycle events
        # ===================================================================
        # Report synthesis cost (one more Claude call)
        await self._paperclip_report_round_costs(
            session.session_id, _pc_issue_id, 4,  # Round 4 = synthesis
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
            log.warning(f"[council:{session_id}] {member.value} API failed: {e}, trying Ollama")
            try:
                return await self._get_ollama_response(member, prompt)
            except Exception as e2:
                log.error(f"[council:{session_id}] {member.value} Ollama also failed: {e2}")
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

    async def _call_claude(self, prompt: str) -> str:
        resp = await self.http_client.post(
            f"{self.anthropic_base_url}/v1/messages",
            headers={
                "x-api-key": self.claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if not content or not isinstance(content, list):
            raise ValueError(f"Unexpected Claude response: {list(data.keys())}")
        return content[0].get("text", "")

    async def _call_grok(self, prompt: str) -> str:
        if not self.xai_api_key:
            raise ValueError("xAI API key not configured")
        resp = await self.http_client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.xai_api_key}"},
            json={
                "model": "grok-3",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8,  # Slightly higher for strategist boldness
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Grok returned no choices: {list(data.keys())}")
        return choices[0].get("message", {}).get("content", "")

    async def _call_gemini(self, prompt: str) -> str:
        if not self.google_api_key:
            raise ValueError("Google API key not configured")
        resp = await self.http_client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": self.google_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError(f"Gemini returned no candidates: {list(data.keys())}")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ValueError("Gemini candidate has no content parts")
        return parts[0].get("text", "")

    async def _call_perplexity(self, prompt: str) -> str:
        if not self.perplexity_api_key:
            raise ValueError("Perplexity API key not configured")
        resp = await self.http_client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {self.perplexity_api_key}"},
            json={
                "model": "sonar-pro",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,  # Lower for fact-checking accuracy
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Perplexity returned no choices: {list(data.keys())}")
        return choices[0].get("message", {}).get("content", "")

    async def _call_gpt(self, prompt: str) -> str:
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not configured")
        resp = await self.http_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,  # Higher for creative divergence
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"GPT returned no choices: {list(data.keys())}")
        return choices[0].get("message", {}).get("content", "")

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
            resp = await self.http_client.post(
                url,
                headers={
                    "api-key": azure_key,
                    "Content-Type": "application/json",
                },
                json={
                    "messages": [
                        {"role": "system", "content": ROLE_SYSTEM_PROMPTS[CouncilRole.ENGINEER]},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.5,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        # Fallback: OpenAI direct
        api_key = self.copilot_api_key or self.openai_api_key
        if not api_key:
            raise ValueError("No Azure, Copilot, or OpenAI API key configured for ENGINEER role")

        resp = await self.http_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": ROLE_SYSTEM_PROMPTS[CouncilRole.ENGINEER]},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Copilot/OpenAI returned no choices: {list(data.keys())}")
        return choices[0].get("message", {}).get("content", "")

    async def _get_ollama_response(self, member: CouncilMember, prompt: str) -> str:
        """Fallback to local Ollama model."""
        model_map = {
            CouncilMember.CLAUDE: "qwen3:32b",
            CouncilMember.GROK: "qwen3:32b",
            CouncilMember.GEMINI: "qwen3:32b",
            CouncilMember.PERPLEXITY: "qwen3:8b",
            CouncilMember.GPT: "qwen3:8b",
            CouncilMember.COPILOT: "deepseek-coder-v2:16b",
        }
        model = model_map.get(member, "qwen3:8b")

        resp = await self.http_client.post(
            f"http://{self.ollama_host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
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
            f'{{"pillar": "NCC", "title": "mandate title", "objective": "objective", "priority": 5, "success_criteria": ["criteria 1"]}}],'
            f' "risk_flags": ["risk 1"],'
            f' "confidence": 80}}\n\n'
            f"Respond with ONLY the JSON object, no markdown fences. "
            f"Be decisive. NATRIX needs clear direction, not hedge-everything caution."
        )

        raw = await self._call_claude(synthesis_prompt)

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
        r3 = session.rounds[-1] if session.rounds else None
        if not r3 or r3.round_type != "convergence":
            r3 = session.rounds[-1]

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
            agree_signals = len(re.findall(
                r'\bagree\b|\bconsensus\b|\balign\b|\bsupport\b|\bconcur\b|\bendorse\b',
                lower
            ))
            disagree_signals = len(re.findall(
                r'\bdisagree\b|\bdissent\b|\boppose\b|\breject\b|\bchallenge\b|\bcontra\b',
                lower
            ))

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
        score.unanimous = agree_count >= total_members and disagree_count == 0
        score.threshold_met = score.agreement_pct >= self.consensus_threshold
        score.dissent_strength = (disagree_count / max(total_members, 1)) * 100

        # Convergence delta: how much positions shifted from R1 to R3
        if len(session.rounds) >= 3:
            r1_confs = list(session.rounds[0].scores.values())
            r3_confs = list(session.rounds[2].scores.values())
            if r1_confs and r3_confs:
                r1_spread = max(r1_confs) - min(r1_confs) if r1_confs else 0
                r3_spread = max(r3_confs) - min(r3_confs) if r3_confs else 0
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
            if any(kw in lower for kw in ["consensus:", "consensus position", "agreement", "common ground"]):
                current_section = "consensus"
                # Check if the content is on the same line after ':'
                after_colon = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                if after_colon and len(after_colon) > 10:
                    consensus = after_colon
                continue
            elif any(kw in lower for kw in ["mandate_recommendation", "recommendation", "action item", "next step", "mandate"]):
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
            consensus = paragraphs[0] if paragraphs else "Synthesis produced but no clear consensus extracted."

        if not recommendations:
            for line in lines:
                stripped = line.strip()
                if any(kw in stripped.lower() for kw in ["should", "recommend", "suggest", "prioritize", "pillar:"]):
                    clean = re.sub(r"^[\d\.\-\*\+]+\s*", "", stripped)
                    if clean and len(clean) > 10:
                        recommendations.append(clean)

        return consensus, recommendations[:15], dissents[:10]

    @staticmethod
    def _extract_confidence(response: str) -> float:
        """Extract confidence score from a member's response."""
        match = re.search(r'(?:CONFIDENCE|confidence)\s*[:=]\s*(\d+)', response)
        if match:
            return min(100.0, max(0.0, float(match.group(1))))
        # Heuristic: count certainty language
        lower = response.lower()
        certainty_words = len(re.findall(r'\bcertain\b|\bconfident\b|\bclearly\b|\bdefinitely\b|\bstrongly\b', lower))
        uncertainty_words = len(re.findall(r'\buncertain\b|\bperhaps\b|\bmaybe\b|\bpossibly\b|\bmight\b|\bunsure\b', lower))
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
                log.warning("[council:paperclip] No PAPERCLIP_COMPANY_ID set, skipping issue creation")
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
            log.info(f"[council:paperclip] Created issue {issue_id} for session {session.session_id}")
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
            self._session_costs[session_id] = self._session_costs.get(session_id, 0) + total_round_cost
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
                f"[council:paperclip] Low consensus ({session.consensus_score.agreement_pct:.0f}%) — "
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
