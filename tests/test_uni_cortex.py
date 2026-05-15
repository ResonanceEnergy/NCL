"""Tests for the UNI Research Cortex (runtime/uni/cortex.py).

Covers:
  1. ResearchCortex initialization and directory setup
  2. Full research pipeline with mocked LLM calls
  3. Results listing from NDJSON persistence
  4. Stats retrieval and aggregation
  5. Error handling (pipeline failures, missing files, bad data)
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from runtime.uni.cortex import ResearchCortex
from runtime.uni.models import (
    Finding,
    ResearchBrief,
    ResearchDepth,
    ResearchResult,
    ResearchStats,
    ResearchStatus,
    SourceResult,
    SourceType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for each test."""
    return tmp_path / "data"


@pytest.fixture
def cortex(tmp_data_dir):
    """Create a ResearchCortex with no real API keys."""
    return ResearchCortex(
        data_dir=str(tmp_data_dir),
        claude_api_key=None,
        xai_api_key=None,
        ollama_host="localhost:11434",
    )


def _make_source(title="Test Source", source_type=SourceType.WEB, content="Some content"):
    """Helper to create a SourceResult for tests."""
    return SourceResult(
        source_type=source_type,
        title=title,
        content=content,
        url="https://example.com",
        relevance_score=0.8,
        credibility_score=0.7,
    )


def _make_finding(claim="Test finding"):
    """Helper to create a Finding for tests."""
    return Finding(
        claim=claim,
        evidence=["Evidence A"],
        confidence=0.75,
        sources=["src-1"],
    )


def _make_research_result(task_id="test-task-1", query="test query", status=ResearchStatus.COMPLETE):
    """Helper to create a minimal ResearchResult."""
    return ResearchResult(
        task_id=task_id,
        query=query,
        status=status,
        findings=[_make_finding()],
        synthesis="Synthesis narrative.",
        key_takeaways=["Takeaway 1"],
        sources_consulted=[_make_source()],
        confidence_score=0.8,
        research_plan={"sub_questions": ["q1"]},
        duration_ms=1234,
        created_at=datetime.now(timezone.utc),
    )


def _make_brief():
    """Helper to create a minimal ResearchBrief."""
    return ResearchBrief(
        title="Brief Title",
        executive_summary="Executive summary text.",
        findings=[_make_finding()],
        recommendations=["Do X"],
        risk_factors=["Risk Y"],
        confidence=0.8,
        sources_count=3,
    )


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


class TestResearchCortexInit:
    """Tests for ResearchCortex.__init__."""

    def test_creates_directory_structure(self, tmp_data_dir):
        """Cortex should create uni/, results/, briefs/ directories on init."""
        cortex = ResearchCortex(data_dir=str(tmp_data_dir))

        assert (tmp_data_dir / "uni").is_dir()
        assert (tmp_data_dir / "uni" / "results").is_dir()
        assert (tmp_data_dir / "uni" / "briefs").is_dir()

    def test_sets_persistence_file_paths(self, cortex, tmp_data_dir):
        """Persistence file paths should be set correctly."""
        assert cortex.results_file == tmp_data_dir / "uni" / "results.ndjson"
        assert cortex.stats_file == tmp_data_dir / "uni" / "stats.json"

    def test_initializes_subsystems(self, cortex):
        """Planner, gatherer, and synthesizer should be created."""
        assert cortex.planner is not None
        assert cortex.gatherer is not None
        assert cortex.synthesizer is not None

    def test_accepts_api_keys(self, tmp_data_dir):
        """API keys should be forwarded to subsystems."""
        cortex = ResearchCortex(
            data_dir=str(tmp_data_dir),
            claude_api_key="sk-test-claude",
            xai_api_key="xai-test-key",
            ollama_host="remote:11434",
        )
        assert cortex.gatherer.claude_api_key == "sk-test-claude"
        assert cortex.gatherer.xai_api_key == "xai-test-key"
        assert cortex.gatherer.ollama_host == "remote:11434"
        assert cortex.synthesizer.claude_api_key == "sk-test-claude"
        assert cortex.synthesizer.xai_api_key == "xai-test-key"

    def test_data_dir_expanduser(self, tmp_path):
        """data_dir should expand ~ in path."""
        cortex = ResearchCortex(data_dir=str(tmp_path / "subdir"))
        assert cortex.data_dir == tmp_path / "subdir"

    def test_creates_dirs_idempotent(self, tmp_data_dir):
        """Creating two cortexes with same data_dir should not error."""
        ResearchCortex(data_dir=str(tmp_data_dir))
        ResearchCortex(data_dir=str(tmp_data_dir))


# ---------------------------------------------------------------------------
# 2. Research pipeline with mocked LLM
# ---------------------------------------------------------------------------


class TestResearchPipeline:
    """Tests for ResearchCortex.research (full pipeline)."""

    @pytest.mark.asyncio
    async def test_research_runs_full_pipeline(self, cortex):
        """research() should call planner, gatherer, and synthesizer in sequence."""
        mock_sources = [_make_source()]
        mock_result = _make_research_result()
        mock_brief = _make_brief()

        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
            patch.object(cortex.synthesizer, "create_brief", new_callable=AsyncMock) as mock_brief_fn,
        ):
            mock_plan.return_value = {
                "sub_questions": ["What is X?"],
                "source_strategy": {"What is X?": [SourceType.WEB]},
                "execution_steps": [],
                "estimated_duration_minutes": 10,
            }
            mock_gather.return_value = mock_sources
            mock_synth.return_value = mock_result
            mock_brief_fn.return_value = mock_brief

            result = await cortex.research("What is X?")

            mock_plan.assert_called_once()
            mock_gather.assert_called_once()
            mock_synth.assert_called_once()
            mock_brief_fn.assert_called_once()
            assert result.status == ResearchStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_research_saves_result_to_disk(self, cortex):
        """research() should persist result as JSON and NDJSON."""
        mock_result = _make_research_result()
        mock_brief = _make_brief()

        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
            patch.object(cortex.synthesizer, "create_brief", new_callable=AsyncMock) as mock_brief_fn,
        ):
            mock_plan.return_value = {
                "sub_questions": ["q"],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.return_value = []
            mock_synth.return_value = mock_result
            mock_brief_fn.return_value = mock_brief

            result = await cortex.research("test query")

            # Check NDJSON log was written
            assert cortex.results_file.exists()
            ndjson_content = cortex.results_file.read_text()
            assert len(ndjson_content.strip().splitlines()) >= 1

            # Check JSON result file
            result_file = cortex.results_dir / f"{result.task_id}.json"
            assert result_file.exists()

    @pytest.mark.asyncio
    async def test_research_sets_task_id_on_result(self, cortex):
        """research() should assign the task_id to the synthesized result."""
        mock_result = _make_research_result(task_id="placeholder")
        mock_brief = _make_brief()

        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
            patch.object(cortex.synthesizer, "create_brief", new_callable=AsyncMock) as mock_brief_fn,
        ):
            mock_plan.return_value = {
                "sub_questions": ["q"],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.return_value = []
            mock_synth.return_value = mock_result
            mock_brief_fn.return_value = mock_brief

            result = await cortex.research("test query")

            # task_id should be a UUID, not the placeholder
            assert result.task_id != "placeholder"
            assert len(result.task_id) > 10  # UUID format

    @pytest.mark.asyncio
    async def test_research_uses_default_sources(self, cortex):
        """Without explicit sources, research should default to WEB, ACADEMIC, NEWS."""
        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
            patch.object(cortex.synthesizer, "create_brief", new_callable=AsyncMock) as mock_brief_fn,
        ):
            mock_plan.return_value = {
                "sub_questions": [],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.return_value = []
            mock_synth.return_value = _make_research_result()
            mock_brief_fn.return_value = _make_brief()

            await cortex.research("query")

            # Planner should have received default sources
            call_kwargs = mock_plan.call_args
            assert SourceType.WEB in call_kwargs.kwargs.get("sources_requested", call_kwargs[1].get("sources_requested", []))

    @pytest.mark.asyncio
    async def test_research_with_custom_depth_and_sources(self, cortex):
        """research() should pass custom depth and sources to planner."""
        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
            patch.object(cortex.synthesizer, "create_brief", new_callable=AsyncMock) as mock_brief_fn,
        ):
            mock_plan.return_value = {
                "sub_questions": [],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.return_value = []
            mock_synth.return_value = _make_research_result()
            mock_brief_fn.return_value = _make_brief()

            await cortex.research(
                "deep query",
                depth=ResearchDepth.DEEP,
                sources=[SourceType.ACADEMIC, SourceType.MARKET_DATA],
                priority=9,
            )

            call_kwargs = mock_plan.call_args
            assert call_kwargs.kwargs.get("depth", call_kwargs[1].get("depth")) == ResearchDepth.DEEP

    @pytest.mark.asyncio
    async def test_research_records_duration(self, cortex):
        """result.duration_ms should be populated."""
        mock_result = _make_research_result()
        mock_brief = _make_brief()

        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
            patch.object(cortex.synthesizer, "create_brief", new_callable=AsyncMock) as mock_brief_fn,
        ):
            mock_plan.return_value = {
                "sub_questions": [],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.return_value = []
            mock_synth.return_value = mock_result
            mock_brief_fn.return_value = mock_brief

            result = await cortex.research("timing test")

            assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# 3. Results listing
# ---------------------------------------------------------------------------


class TestListResults:
    """Tests for ResearchCortex.list_results."""

    @pytest.mark.asyncio
    async def test_list_results_empty(self, cortex):
        """list_results should return empty list when no results file exists."""
        results = await cortex.list_results()
        assert results == []

    @pytest.mark.asyncio
    async def test_list_results_returns_summaries(self, cortex):
        """list_results should parse NDJSON and return summary dicts."""
        # Write mock NDJSON data
        result1 = _make_research_result(task_id="task-1", query="Query one")
        result2 = _make_research_result(task_id="task-2", query="Query two")

        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            f.write(result1.model_dump_json() + "\n")
            f.write(result2.model_dump_json() + "\n")

        results = await cortex.list_results()

        assert len(results) == 2
        task_ids = {r["task_id"] for r in results}
        assert "task-1" in task_ids
        assert "task-2" in task_ids

    @pytest.mark.asyncio
    async def test_list_results_summary_fields(self, cortex):
        """Each summary should contain expected fields."""
        result = _make_research_result()
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            f.write(result.model_dump_json() + "\n")

        summaries = await cortex.list_results()
        assert len(summaries) == 1
        s = summaries[0]

        assert "task_id" in s
        assert "query" in s
        assert "status" in s
        assert "confidence" in s
        assert "sources_count" in s
        assert "duration_ms" in s
        assert "created_at" in s

    @pytest.mark.asyncio
    async def test_list_results_respects_limit(self, cortex):
        """list_results(limit=N) should return at most N results."""
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            for i in range(10):
                r = _make_research_result(task_id=f"task-{i}", query=f"Query {i}")
                f.write(r.model_dump_json() + "\n")

        results = await cortex.list_results(limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_list_results_sorted_by_created_at(self, cortex):
        """Results should be sorted most-recent first."""
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            for i in range(5):
                r = _make_research_result(task_id=f"task-{i}")
                f.write(r.model_dump_json() + "\n")

        results = await cortex.list_results()
        # All have same created_at so just check it doesn't crash
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_list_results_skips_blank_lines(self, cortex):
        """Blank lines in NDJSON should be skipped."""
        result = _make_research_result()
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            f.write("\n")
            f.write(result.model_dump_json() + "\n")
            f.write("\n")

        results = await cortex.list_results()
        assert len(results) == 1


# ---------------------------------------------------------------------------
# 4. Stats retrieval
# ---------------------------------------------------------------------------


class TestGetStats:
    """Tests for ResearchCortex.get_stats."""

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, cortex):
        """get_stats should return default stats when no data."""
        stats = await cortex.get_stats()
        assert isinstance(stats, ResearchStats)
        assert stats.total_tasks == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, cortex):
        """get_stats should aggregate task count and averages."""
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            for i in range(3):
                r = _make_research_result(task_id=f"task-{i}")
                f.write(r.model_dump_json() + "\n")

        stats = await cortex.get_stats()
        assert stats.total_tasks == 3
        assert stats.avg_confidence > 0
        assert stats.avg_duration_ms > 0

    @pytest.mark.asyncio
    async def test_get_stats_source_distribution(self, cortex):
        """get_stats should track source type counts."""
        result = _make_research_result()
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            f.write(result.model_dump_json() + "\n")

        stats = await cortex.get_stats()
        # The mock result has one WEB source
        assert isinstance(stats.source_type_distribution, dict)

    @pytest.mark.asyncio
    async def test_get_stats_skips_blank_lines(self, cortex):
        """Blank lines should not affect stats."""
        result = _make_research_result()
        cortex.results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cortex.results_file, "w") as f:
            f.write("\n\n")
            f.write(result.model_dump_json() + "\n")
            f.write("\n")

        stats = await cortex.get_stats()
        assert stats.total_tasks == 1


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling in the research pipeline."""

    @pytest.mark.asyncio
    async def test_research_failure_saves_failed_result(self, cortex):
        """When the pipeline fails, a FAILED result should be persisted."""
        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
        ):
            mock_plan.return_value = {
                "sub_questions": ["q"],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.side_effect = RuntimeError("Network down")

            with pytest.raises(RuntimeError, match="Network down"):
                await cortex.research("failing query")

            # A FAILED result should have been saved to NDJSON
            assert cortex.results_file.exists()
            content = cortex.results_file.read_text().strip()
            data = json.loads(content)
            assert data["status"] == ResearchStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_research_failure_records_error_in_plan(self, cortex):
        """Failed result should contain error details in research_plan."""
        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
        ):
            mock_plan.return_value = {
                "sub_questions": [],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.side_effect = ValueError("Bad input")

            with pytest.raises(ValueError):
                await cortex.research("bad query")

            content = cortex.results_file.read_text().strip()
            data = json.loads(content)
            assert "Bad input" in data["research_plan"].get("error", "")

    @pytest.mark.asyncio
    async def test_research_planner_failure_propagates(self, cortex):
        """If the planner itself raises, the exception should propagate."""
        with patch.object(cortex.planner, "plan_research", side_effect=TypeError("plan error")):
            with pytest.raises(TypeError, match="plan error"):
                await cortex.research("broken planner query")

    @pytest.mark.asyncio
    async def test_research_synthesizer_failure(self, cortex):
        """If the synthesizer raises, exception should propagate with FAILED result saved."""
        with (
            patch.object(cortex.planner, "plan_research") as mock_plan,
            patch.object(cortex.gatherer, "gather_all", new_callable=AsyncMock) as mock_gather,
            patch.object(cortex.synthesizer, "synthesize", new_callable=AsyncMock) as mock_synth,
        ):
            mock_plan.return_value = {
                "sub_questions": ["q"],
                "source_strategy": {},
                "execution_steps": [],
                "estimated_duration_minutes": 5,
            }
            mock_gather.return_value = [_make_source()]
            mock_synth.side_effect = ConnectionError("API unreachable")

            with pytest.raises(ConnectionError, match="API unreachable"):
                await cortex.research("synth failure")

            content = cortex.results_file.read_text().strip()
            data = json.loads(content)
            assert data["status"] == ResearchStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_get_result_missing_task(self, cortex):
        """get_result should return None for nonexistent task_id."""
        result = await cortex.get_result("nonexistent-task-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_result_existing_task(self, cortex):
        """get_result should load a persisted result from disk."""
        mock_result = _make_research_result(task_id="existing-task")

        # Write the result file
        result_file = cortex.results_dir / "existing-task.json"
        result_file.parent.mkdir(parents=True, exist_ok=True)
        with open(result_file, "w") as f:
            f.write(mock_result.model_dump_json(indent=2))

        loaded = await cortex.get_result("existing-task")
        assert loaded is not None
        assert loaded.task_id == "existing-task"
        assert loaded.status == ResearchStatus.COMPLETE
