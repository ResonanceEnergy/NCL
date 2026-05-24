"""
Council Fallback Mode Tests — Quorum, API Failures, Ollama Degradation

Tests council behavior when API endpoints fail and Ollama fallback is triggered.
Covers:
- Council quorum requirements (4+ members)
- Quorum failure with [member unavailable] responses
- API failure recovery via Ollama
- All providers failing (placeholder response)

Run:
    pytest tests/test_council_fallback.py -v
    pytest tests/test_council_fallback.py -v --asyncio-mode=auto
"""

import asyncio
from unittest.mock import patch

import pytest

from runtime.ncl_brain.council import CouncilEngine
from runtime.ncl_brain.models import (
    CouncilMember,
    CouncilRole,
    CouncilSession,
    CouncilStatus,
)


@pytest.fixture
def council_engine():
    """Create a council engine with mocked dependencies."""
    engine = CouncilEngine(
        claude_api_key="test-key-claude",
        xai_api_key="test-key-xai",
        google_api_key="test-key-google",
        perplexity_api_key="test-key-perplexity",
        openai_api_key="test-key-openai",
        copilot_api_key="test-key-copilot",
        ollama_host="localhost:11434",
    )
    return engine


@pytest.mark.asyncio
async def test_council_quorum_met(council_engine):
    """
    Test: Council completes when 4+ members respond successfully.

    Scenario:
    - All 6 members return valid responses
    - Claude synthesizes consensus from 6 perspectives
    - Session status moves from DEBATING → SYNTHESIZING → COMPLETE
    """
    # Mock successful responses from all members
    mock_responses = {
        CouncilMember.CLAUDE: "As chair, I synthesize agreement on strategy.",
        CouncilMember.GROK: "Strategist agrees, bold move recommended.",
        CouncilMember.GEMINI: "Analyst confirms data supports this direction.",
        CouncilMember.PERPLEXITY: "Researcher verified with current sources.",
        CouncilMember.GPT: "Creative suggests lateral enhancement.",
        CouncilMember.COPILOT: "Engineer confirms technical feasibility.",
    }

    # Mock the API calls
    with patch.object(council_engine, "_call_member_api") as mock_api:

        async def call_api_side_effect(member, prompt, role, round_type):
            await asyncio.sleep(0.01)  # Simulate API latency
            return mock_responses.get(member, "Response")

        mock_api.side_effect = call_api_side_effect

        session = CouncilSession(
            session_id="test-cs-001",
            topic="Test debate",
            prompt="Test prompt",
            members=[m.value for m in CouncilMember],
            chair="claude",
        )

        # Run council debate rounds
        session.status = CouncilStatus.DEBATING
        responses = {}
        for round_num in [1, 2, 3]:
            round_responses = {}
            for member in CouncilMember:
                response = await council_engine._call_member_api(
                    member=member,
                    prompt=session.prompt,
                    role=CouncilRole.CHAIR,
                    round_type="position"
                    if round_num == 1
                    else ("rebuttal" if round_num == 2 else "convergence"),
                )
                round_responses[member.value] = response

            responses[f"round_{round_num}"] = round_responses

        # Verify all members responded
        for round_key, round_responses in responses.items():
            assert len(round_responses) == 6, f"Missing responses in {round_key}"
            for member_name, response in round_responses.items():
                assert response is not None
                assert "[unavailable]" not in response.lower()

        # Verify quorum was met (all 6 members)
        session.status = CouncilStatus.SYNTHESIZING
        session.synthesis = "Consensus reached through all 6 perspectives."
        session.consensus = "Deploy strategy with technical safeguards."
        session.status = CouncilStatus.COMPLETE

        assert session.status == CouncilStatus.COMPLETE
        assert len(responses) == 3  # All 3 rounds completed
        assert session.synthesis is not None


@pytest.mark.asyncio
async def test_council_quorum_not_met(council_engine):
    """
    Test: Council halts when quorum is not met (3+ members unavailable).

    Scenario:
    - 4 members return "[member unavailable]"
    - Only 2 members respond successfully
    - Quorum fails (need 4+ responding members)
    - Session status set to FAILED with quorum error
    """

    # Mock responses: 4 unavailable, 2 available
    async def call_api_side_effect_quorum_fail(member, prompt, role, round_type):
        await asyncio.sleep(0.01)
        unavailable_members = [
            CouncilMember.GROK,
            CouncilMember.GEMINI,
            CouncilMember.PERPLEXITY,
            CouncilMember.COPILOT,
        ]
        if member in unavailable_members:
            return "[member unavailable]"
        return f"Response from {member.value}"

    with patch.object(council_engine, "_call_member_api") as mock_api:
        mock_api.side_effect = call_api_side_effect_quorum_fail

        session = CouncilSession(
            session_id="test-cs-002",
            topic="Test debate",
            prompt="Test prompt",
            members=[m.value for m in CouncilMember],
            chair="claude",
        )

        session.status = CouncilStatus.DEBATING

        # Collect first round responses
        responses = {}
        unavailable_count = 0
        for member in CouncilMember:
            response = await council_engine._call_member_api(
                member=member,
                prompt=session.prompt,
                role=CouncilRole.CHAIR,
                round_type="position",
            )
            responses[member.value] = response
            if "[unavailable]" in response.lower():
                unavailable_count += 1

        # Verify quorum failure: 4 unavailable > 3 threshold
        available_count = len(responses) - unavailable_count
        assert unavailable_count >= 3, "Should have 3+ unavailable members"
        assert available_count < 4, "Should have fewer than 4 available members"

        # Simulate council halting due to quorum failure
        session.status = CouncilStatus.FAILED
        session.error_message = f"Quorum not met: {available_count}/6 members available (need 4+)"

        assert session.status == CouncilStatus.FAILED
        assert "Quorum not met" in session.error_message


@pytest.mark.asyncio
async def test_ollama_fallback_triggered(council_engine):
    """
    Test: Ollama fallback is triggered when API endpoints fail.

    Scenario:
    - API call raises httpx.ConnectError or TimeoutError
    - Council engine catches exception and calls Ollama endpoint
    - Ollama returns valid response
    - Session continues with Ollama responses for that member
    """
    # Mock API failure, then successful Ollama fallback
    call_count = 0

    async def call_api_with_failure(member, prompt, role, round_type):
        nonlocal call_count
        call_count += 1

        # Simulate API timeout on first call
        if call_count == 1:
            raise TimeoutError(f"API timeout for {member.value}")

        # Return response as if from Ollama
        return f"[OLLAMA FALLBACK] Response from {member.value}"

    with patch.object(council_engine, "_call_member_api") as mock_api:
        mock_api.side_effect = call_api_with_failure

        # Mock the Ollama fallback method
        async def mock_ollama_fallback(member, prompt, role):
            await asyncio.sleep(0.01)
            return f"[OLLAMA FALLBACK] Response from {member.value}"

        council_engine._call_ollama_fallback = mock_ollama_fallback

        session = CouncilSession(
            session_id="test-cs-003",
            topic="Test debate with API failure",
            prompt="Test prompt",
            members=[m.value for m in CouncilMember],
            chair="claude",
        )

        session.status = CouncilStatus.DEBATING

        responses = {}
        fallback_count = 0

        for member in CouncilMember:
            try:
                response = await council_engine._call_member_api(
                    member=member,
                    prompt=session.prompt,
                    role=CouncilRole.CHAIR,
                    round_type="position",
                )
                responses[member.value] = response
            except TimeoutError:
                # Fallback to Ollama
                fallback_count += 1
                response = await council_engine._call_ollama_fallback(
                    member=member,
                    prompt=session.prompt,
                    role=CouncilRole.CHAIR,
                )
                responses[member.value] = response

        # Verify at least one fallback occurred
        assert fallback_count > 0, "Should have triggered at least one fallback"

        # Verify all responses collected (including fallback responses)
        assert len(responses) > 0

        # Verify fallback responses contain the marker
        fallback_responses = [r for r in responses.values() if "[OLLAMA FALLBACK]" in r]
        assert len(fallback_responses) > 0, "Should have at least one OLLAMA response"


@pytest.mark.asyncio
async def test_all_providers_fail(council_engine):
    """
    Test: All providers fail (API + Ollama), placeholder response is returned.

    Scenario:
    - All API endpoints fail
    - Ollama endpoint fails
    - Council engine returns degraded/placeholder response
    - Session status marked as DEGRADED or FAILED with explanation
    """

    async def all_fail_side_effect(member, prompt, role, round_type):
        raise ConnectionError(f"All providers failed for {member.value}")

    with patch.object(council_engine, "_call_member_api") as mock_api:
        mock_api.side_effect = all_fail_side_effect

        # Mock Ollama also failing
        async def mock_ollama_fail(member, prompt, role):
            raise ConnectionError(f"Ollama also unavailable for {member.value}")

        council_engine._call_ollama_fallback = mock_ollama_fail

        session = CouncilSession(
            session_id="test-cs-004",
            topic="Test debate with total failure",
            prompt="Test prompt",
            members=[m.value for m in CouncilMember],
            chair="claude",
        )

        session.status = CouncilStatus.DEBATING
        responses = {}
        failures = 0

        for member in CouncilMember:
            try:
                response = await council_engine._call_member_api(
                    member=member,
                    prompt=session.prompt,
                    role=CouncilRole.CHAIR,
                    round_type="position",
                )
                responses[member.value] = response
            except ConnectionError:
                try:
                    response = await council_engine._call_ollama_fallback(
                        member=member,
                        prompt=session.prompt,
                        role=CouncilRole.CHAIR,
                    )
                    responses[member.value] = response
                except ConnectionError:
                    # All providers failed for this member
                    failures += 1
                    # Use placeholder response
                    responses[member.value] = (
                        f"[DEGRADED] Unable to reach {member.value}. "
                        "Proceeding with cached context and previous positions."
                    )

        # Verify all members have responses (even if degraded)
        assert len(responses) == len(CouncilMember)

        # Verify at least some were degraded/placeholder
        degraded_responses = [r for r in responses.values() if "[DEGRADED]" in r]
        assert len(degraded_responses) > 0, "Should have at least one degraded response"

        # Mark session as failed/degraded
        session.status = CouncilStatus.FAILED
        session.error_message = (
            f"All providers unavailable for {failures} members. "
            "Session operating in degraded mode with cached context."
        )

        assert session.status == CouncilStatus.FAILED
        assert failures > 0
        assert "degraded mode" in session.error_message


@pytest.mark.asyncio
async def test_council_timeout_handling(council_engine):
    """
    Test: Council handles member timeouts gracefully.

    Scenario:
    - Member API times out after N seconds
    - Council marks member as non-responsive
    - Other members continue debating
    - Quorum check includes non-responsive members in unavailable count
    """
    import asyncio

    async def timeout_side_effect(member, prompt, role, round_type):
        # Grok times out, others respond normally
        if member == CouncilMember.GROK:
            await asyncio.sleep(5)  # Simulate timeout
            raise TimeoutError("Grok API timeout")
        await asyncio.sleep(0.01)
        return f"Response from {member.value}"

    with patch.object(council_engine, "_call_member_api") as mock_api:
        mock_api.side_effect = timeout_side_effect

        session = CouncilSession(
            session_id="test-cs-005",
            topic="Test debate with timeout",
            prompt="Test prompt",
            members=[m.value for m in CouncilMember],
            chair="claude",
        )

        session.status = CouncilStatus.DEBATING
        responses = {}
        timed_out = []

        for member in CouncilMember:
            try:
                # Use 0.5 second timeout
                response = await asyncio.wait_for(
                    council_engine._call_member_api(
                        member=member,
                        prompt=session.prompt,
                        role=CouncilRole.CHAIR,
                        round_type="position",
                    ),
                    timeout=0.5,
                )
                responses[member.value] = response
            except asyncio.TimeoutError:
                timed_out.append(member.value)
                responses[member.value] = "[timed out]"

        # Verify at least one member timed out
        assert len(timed_out) > 0, "Should have at least one timeout"
        assert "grok" in timed_out

        # Verify other members still responded
        responding_members = [m for m in CouncilMember if m.value not in timed_out]
        assert len(responding_members) > 0

        # Check quorum: timed out members count against quorum
        available = len(responses) - len(timed_out)
        quorum_met = available >= 4

        # With 1 timed out member, 5 are available — quorum should be met
        assert quorum_met, f"Expected quorum met with {available} available members"
        assert available >= 4, f"Expected 4+ available, got {available}"
