"""Tests for NCL council runner."""
import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from runtime.council_runner.models import (
    AgentRole,
    AgentConfig,
    AgentOutput,
    ConsensusResult,
    CouncilRunRecord,
    ReplayConfig,
)
from runtime.council_runner.agents import get_agent_configs, _synthesize_consensus
from runtime.council_runner.store import CouncilRunStore


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_agent_roles():
    """Test agent role enum values."""
    assert AgentRole.PLANNER == "planner"
    assert AgentRole.SKEPTIC == "skeptic"
    assert AgentRole.RISK == "risk"


def test_agent_configs_complete():
    """Test that agent configs are complete and well-formed."""
    configs = get_agent_configs()

    # Should have exactly three agents
    assert len(configs) == 3
    assert AgentRole.PLANNER in configs
    assert AgentRole.SKEPTIC in configs
    assert AgentRole.RISK in configs

    # Each config should be valid
    for role, config in configs.items():
        assert isinstance(config, AgentConfig)
        assert config.role == role
        assert config.system_prompt is not None
        assert len(config.system_prompt) > 0
        assert config.temperature >= 0.0
        assert config.temperature <= 1.0
        assert config.max_tokens > 0


def test_agent_config_properties():
    """Test individual agent config properties."""
    configs = get_agent_configs()

    planner = configs[AgentRole.PLANNER]
    skeptic = configs[AgentRole.SKEPTIC]
    risk = configs[AgentRole.RISK]

    # Planner should focus on plans
    assert "plan" in planner.system_prompt.lower() or "strategy" in planner.system_prompt.lower()

    # Skeptic should focus on challenges
    assert "challenge" in skeptic.system_prompt.lower() or "skeptic" in skeptic.system_prompt.lower()

    # Risk should focus on risks
    assert "risk" in risk.system_prompt.lower()


def test_agent_output_creation():
    """Test creating an agent output."""
    output = AgentOutput(
        role=AgentRole.PLANNER,
        response_text="Here is my analysis...",
        confidence=0.85,
        key_points=["Point 1", "Point 2"],
        dissent_notes=[],
        risks_identified=[],
        model_used="claude-3-opus"
    )

    assert output.role == AgentRole.PLANNER
    assert output.response_text == "Here is my analysis..."
    assert output.confidence == 0.85
    assert len(output.key_points) == 2
    assert output.model_used == "claude-3-opus"
    assert output.timestamp is not None


def test_consensus_result_creation():
    """Test creating a consensus result."""
    consensus = ConsensusResult(
        consensus_text="The council agrees on the following...",
        consensus_score=75,
        agreement_areas=["Market risk assessment", "Timeline"],
        dissent_areas=["Resource allocation"],
        risk_flags=["Execution risk", "Market volatility"],
        recommendations=["Hedge position", "Monitor closely"]
    )

    assert consensus.consensus_score == 75
    assert len(consensus.agreement_areas) == 2
    assert len(consensus.dissent_areas) == 1
    assert len(consensus.risk_flags) == 2


def test_consensus_synthesis_agreement():
    """Test consensus synthesis when agents agree."""
    # Create outputs simulating agreement
    planner_output = AgentOutput(
        role=AgentRole.PLANNER,
        response_text="Execute the plan",
        confidence=0.9,
        key_points=["Execute plan", "Monitor results"]
    )

    skeptic_output = AgentOutput(
        role=AgentRole.SKEPTIC,
        response_text="Plan seems sound",
        confidence=0.85,
        dissent_notes=[],
        key_points=["Execute plan"]
    )

    risk_output = AgentOutput(
        role=AgentRole.RISK,
        response_text="Risks are manageable",
        confidence=0.8,
        risks_identified=["Market risk (low)"],
        key_points=["Monitor results"]
    )

    outputs = [planner_output, skeptic_output, risk_output]

    # Synthesize consensus
    consensus = _synthesize_consensus(outputs)

    assert isinstance(consensus, ConsensusResult)
    assert consensus.consensus_score >= 50
    assert len(consensus.agreement_areas) > 0


def test_consensus_synthesis_dissent():
    """Test consensus synthesis when agents disagree."""
    planner_output = AgentOutput(
        role=AgentRole.PLANNER,
        response_text="Execute immediately",
        confidence=0.9
    )

    skeptic_output = AgentOutput(
        role=AgentRole.SKEPTIC,
        response_text="Hold on, there are risks",
        confidence=0.8,
        dissent_notes=["Insufficient due diligence"]
    )

    risk_output = AgentOutput(
        role=AgentRole.RISK,
        response_text="High execution risk",
        confidence=0.85,
        risks_identified=["Market volatility", "Execution risk"]
    )

    outputs = [planner_output, skeptic_output, risk_output]

    consensus = _synthesize_consensus(outputs)

    assert isinstance(consensus, ConsensusResult)
    # Should note dissent areas
    assert len(consensus.dissent_areas) > 0 or len(consensus.risk_flags) > 0


def test_consensus_risk_flags():
    """Test that consensus captures risk flags."""
    outputs = [
        AgentOutput(
            role=AgentRole.RISK,
            response_text="Multiple risks identified",
            risks_identified=["Market risk", "Execution risk", "Regulatory risk"]
        )
    ]

    consensus = _synthesize_consensus(outputs)

    assert len(consensus.risk_flags) > 0


def test_council_run_record_creation():
    """Test creating a council run record."""
    record = CouncilRunRecord(
        run_id="run-001",
        topic="Market analysis",
        prompt="Analyze recent volatility",
        agent_outputs=[],
        consensus=ConsensusResult(
            consensus_text="Consensus text",
            consensus_score=80
        ),
        replay_config=None
    )

    assert record.run_id == "run-001"
    assert record.topic == "Market analysis"
    assert record.prompt == "Analyze recent volatility"
    assert record.consensus.consensus_score == 80
    assert record.timestamp is not None


@pytest.mark.asyncio
async def test_store_save_load(temp_data_dir):
    """Test saving and loading council runs."""
    store = CouncilRunStore(temp_data_dir)

    record = CouncilRunRecord(
        run_id="run-001",
        topic="Test topic",
        prompt="Test prompt",
        agent_outputs=[],
        consensus=ConsensusResult(
            consensus_text="Test consensus",
            consensus_score=75
        )
    )

    # Save
    await store.save_run(record)

    # Load
    loaded = await store.get_run("run-001")

    assert loaded.run_id == record.run_id
    assert loaded.topic == record.topic
    assert loaded.consensus.consensus_score == 75


@pytest.mark.asyncio
async def test_store_list(temp_data_dir):
    """Test listing council runs."""
    store = CouncilRunStore(temp_data_dir)

    # Save multiple runs
    for i in range(3):
        record = CouncilRunRecord(
            run_id=f"run-{i:03d}",
            topic=f"Topic {i}",
            prompt=f"Prompt {i}",
            agent_outputs=[],
            consensus=ConsensusResult(
                consensus_text=f"Consensus {i}",
                consensus_score=50 + i * 10
            )
        )
        await store.save_run(record)

    # List runs
    runs = await store.list_runs(limit=10)

    assert len(runs) >= 3


@pytest.mark.asyncio
async def test_store_search(temp_data_dir):
    """Test searching council runs."""
    store = CouncilRunStore(temp_data_dir)

    # Save runs with different topics
    for topic in ["Market", "Risk", "Portfolio"]:
        record = CouncilRunRecord(
            run_id=f"run-{topic.lower()}",
            topic=topic,
            prompt=f"Analyze {topic}",
            agent_outputs=[],
            consensus=ConsensusResult(
                consensus_text=f"Analysis of {topic}",
                consensus_score=80
            )
        )
        await store.save_run(record)

    # Search for runs
    results = await store.search_runs("Market", limit=10)

    assert len(results) >= 1
    assert any("market" in r.topic.lower() for r in results)


@pytest.mark.asyncio
async def test_store_provenance(temp_data_dir):
    """Test that run records track full provenance."""
    store = CouncilRunStore(temp_data_dir)

    planner_output = AgentOutput(
        role=AgentRole.PLANNER,
        response_text="Plan text",
        confidence=0.9,
        model_used="claude-3-opus"
    )

    consensus = ConsensusResult(
        consensus_text="Consensus",
        consensus_score=80
    )

    record = CouncilRunRecord(
        run_id="run-prov-001",
        topic="Test",
        prompt="Test prompt",
        agent_outputs=[planner_output],
        consensus=consensus,
        provenance={
            "pump_id": "pump-123",
            "mandate_id": "mandate-456"
        }
    )

    await store.save_run(record)
    loaded = await store.get_run("run-prov-001")

    # Verify provenance is maintained
    assert loaded.provenance.get("pump_id") == "pump-123"
    assert loaded.provenance.get("mandate_id") == "mandate-456"
    assert len(loaded.agent_outputs) == 1


def test_council_run_record_model():
    """Test CouncilRunRecord model validation."""
    record = CouncilRunRecord(
        run_id="run-001",
        topic="Test topic",
        prompt="Test prompt",
        agent_outputs=[],
        consensus=ConsensusResult(
            consensus_text="Text",
            consensus_score=50
        ),
        total_duration_ms=1234
    )

    assert record.run_id == "run-001"
    assert record.total_duration_ms == 1234


def test_replay_config():
    """Test creating a replay config."""
    replay = ReplayConfig(
        run_id="run-001",
        replay_seed="seed-123",
        force_models={
            AgentRole.PLANNER: "claude-3-opus",
            AgentRole.SKEPTIC: "claude-3-sonnet"
        },
        temperature_override=0.3
    )

    assert replay.run_id == "run-001"
    assert replay.replay_seed == "seed-123"
    assert replay.force_models[AgentRole.PLANNER] == "claude-3-opus"
    assert replay.temperature_override == 0.3
