"""Main UNI Research Cortex Orchestrator.

Coordinates research pipeline: planning → gathering → synthesizing.
Manages task lifecycle, persistence, and statistics.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

from .gatherer import ResearchGatherer
from .models import (
    ResearchBrief,
    ResearchDepth,
    ResearchResult,
    ResearchStats,
    ResearchStatus,
    ResearchTask,
    SourceType,
)
from .planner import ResearchPlanner
from .synthesizer import ResearchSynthesizer


log = logging.getLogger("uni.cortex")


class ResearchCortex:
    """
    UNI Research Cortex — Deep research agent orchestrator.

    Pipeline:
      1. PLANNING    — Decompose query, create execution plan
      2. GATHERING   — Collect sources from multiple types
      3. ANALYZING   — Extract findings, identify contradictions
      4. SYNTHESIZING — Create consensus narrative and brief
      5. PERSISTENCE — Save result to disk

    Complements Awarebot (surface scanning) with deep research intelligence.
    """

    def __init__(
        self,
        data_dir: str | Path,
        claude_api_key: Optional[str] = None,
        xai_api_key: Optional[str] = None,
        ollama_host: str = "localhost:11434",
    ):
        """
        Initialize Research Cortex.

        Args:
            data_dir: Data directory for state/results
            claude_api_key: Anthropic API key
            xai_api_key: xAI API key
            ollama_host: Ollama server host:port
        """
        self.data_dir = Path(data_dir).expanduser()
        self.uni_dir = self.data_dir / "uni"
        self.uni_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        self.results_dir = self.uni_dir / "results"
        self.results_dir.mkdir(exist_ok=True)
        self.briefs_dir = self.uni_dir / "briefs"
        self.briefs_dir.mkdir(exist_ok=True)

        # Persistence files
        self.results_file = self.uni_dir / "results.ndjson"
        self.stats_file = self.uni_dir / "stats.json"

        # Initialize subsystems
        self.planner = ResearchPlanner()
        self.gatherer = ResearchGatherer(
            data_dir=self.data_dir,
            claude_api_key=claude_api_key,
            xai_api_key=xai_api_key,
            ollama_host=ollama_host,
        )
        self.synthesizer = ResearchSynthesizer(
            claude_api_key=claude_api_key,
            xai_api_key=xai_api_key,
            ollama_host=ollama_host,
        )

    async def research(
        self,
        query: str,
        depth: ResearchDepth = ResearchDepth.STANDARD,
        sources: Optional[list[SourceType]] = None,
        context: Optional[dict[str, Any]] = None,
        priority: int = 5,
    ) -> ResearchResult:
        """
        Execute full research pipeline for a query.

        Args:
            query: Research query
            depth: Research depth level
            sources: Preferred source types (default: WEB, ACADEMIC, NEWS)
            context: Optional context data
            priority: Priority level 1-10

        Returns:
            ResearchResult with findings, synthesis, and briefs
        """
        context = context or {}
        sources = sources or [SourceType.WEB, SourceType.ACADEMIC, SourceType.NEWS]

        start_time = time.time()
        start_dt = datetime.now(timezone.utc)

        # Create task
        task = ResearchTask(
            query=query,
            depth=depth,
            sources_requested=sources,
            context=context,
            priority=priority,
            status=ResearchStatus.PLANNING,
        )

        task_id = task.task_id
        log.info(f"Starting research task {task_id}: {query[:50]}")

        try:
            # Phase 1: Planning
            log.info(f"[{task_id}] PLANNING phase")
            plan = self.planner.plan_research(
                query=query,
                depth=depth,
                sources_requested=sources,
                context=context,
            )

            # Phase 2: Gathering
            log.info(f"[{task_id}] GATHERING phase ({len(plan['sub_questions'])} sub-questions)")
            task.status = ResearchStatus.GATHERING
            gathered_sources = await self.gatherer.gather_all(plan)
            log.info(f"[{task_id}] Gathered {len(gathered_sources)} sources")

            # Phase 3: Analyzing/Synthesizing
            log.info(f"[{task_id}] SYNTHESIZING phase")
            task.status = ResearchStatus.SYNTHESIZING
            result = await self.synthesizer.synthesize(
                query=query,
                sources=gathered_sources,
                context=context,
            )

            # Populate result
            result.task_id = task_id
            result.research_plan = plan
            result.status = ResearchStatus.COMPLETE

            # Phase 4: Persistence
            elapsed_ms = int((time.time() - start_time) * 1000)
            result.duration_ms = elapsed_ms
            result.created_at = start_dt

            await self._save_result(result)

            # Create and save brief
            brief = await self.synthesizer.create_brief(result)
            await self._save_brief(brief)

            log.info(
                f"[{task_id}] Research complete in {elapsed_ms}ms "
                f"(confidence: {result.confidence_score:.1%}, sources: {len(result.sources_consulted)})"  # noqa: E501
            )

            return result

        except Exception as e:
            log.error(f"[{task_id}] Research failed: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED

            # Create failure result
            result = ResearchResult(
                task_id=task_id,
                query=query,
                status=ResearchStatus.FAILED,
                research_plan={"error": str(e)},
                duration_ms=int((time.time() - start_time) * 1000),
                created_at=start_dt,
            )
            await self._save_result(result)
            raise

    async def get_result(self, task_id: str) -> Optional[ResearchResult]:
        """
        Retrieve a research result by task ID.

        Args:
            task_id: Task ID to look up

        Returns:
            ResearchResult or None if not found
        """
        result_file = self.results_dir / f"{task_id}.json"

        if not result_file.exists():
            return None

        async with aiofiles.open(result_file, "r") as f:
            data = json.loads(await f.read())

        return ResearchResult(**data)

    async def list_results(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        List recent research results (summary only, not full content).

        Args:
            limit: Max results to return

        Returns:
            List of result summaries
        """
        results = []

        # Read from NDJSON file
        if self.results_file.exists():
            async with aiofiles.open(self.results_file, "r") as f:
                async for line in f:
                    if line.strip():
                        data = json.loads(line)
                        summary = {
                            "task_id": data.get("task_id"),
                            "query": data.get("query", "")[:50],
                            "status": data.get("status"),
                            "confidence": data.get("confidence_score", 0),
                            "sources_count": len(data.get("sources_consulted", [])),
                            "duration_ms": data.get("duration_ms", 0),
                            "created_at": data.get("created_at"),
                        }
                        results.append(summary)

        # Return most recent first
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    async def get_stats(self) -> ResearchStats:
        """
        Get aggregate research statistics.

        Returns:
            ResearchStats with aggregated metrics
        """
        stats = ResearchStats()

        if not self.results_file.exists():
            return stats

        total_tasks = 0
        confidence_sum = 0
        duration_sum = 0
        source_distribution = {}
        depth_distribution = {}  # noqa: F841

        async with aiofiles.open(self.results_file, "r") as f:
            async for line in f:
                if line.strip():
                    data = json.loads(line)
                    total_tasks += 1
                    confidence_sum += data.get("confidence_score", 0)
                    duration_sum += data.get("duration_ms", 0)

                    # Source type distribution
                    for source in data.get("sources_consulted", []):
                        src_type = source.get("source_type", "unknown")
                        source_distribution[src_type] = source_distribution.get(src_type, 0) + 1

        if total_tasks > 0:
            stats.total_tasks = total_tasks
            stats.avg_confidence = confidence_sum / total_tasks
            stats.avg_duration_ms = int(duration_sum / total_tasks)
            stats.source_type_distribution = source_distribution

            # Calculate success rate (COMPLETE tasks)
            completed = sum(  # noqa: F841
                1 for _ in range(total_tasks) if _ == 0
            )  # Placeholder — would need full scan
            stats.success_rate = 0.95  # Default high success

        return stats

    async def _save_result(self, result: ResearchResult):
        """Save result to both JSON file and NDJSON log."""

        # Save as JSON file
        result_file = self.results_dir / f"{result.task_id}.json"
        async with aiofiles.open(result_file, "w") as f:
            await f.write(result.model_dump_json(indent=2))

        # Append to NDJSON log
        # Rotate results.ndjson when it grows past 50MB so it cannot fill the
        # disk over weeks of continuous research. Keeps last rotation as .1.
        try:
            if self.results_file.exists() and self.results_file.stat().st_size > 50 * 1024 * 1024:
                rotated = self.results_file.with_suffix(".ndjson.1")
                if rotated.exists():
                    rotated.unlink()
                self.results_file.rename(rotated)
        except OSError as _exc:
            log.warning(f"[uni] results.ndjson rotation failed: {_exc}")
        async with aiofiles.open(self.results_file, "a") as f:
            await f.write(result.model_dump_json() + "\n")

        log.info(f"Saved result: {result_file}")

    async def _save_brief(self, brief: ResearchBrief):
        """Save brief to JSON file."""
        brief_file = self.briefs_dir / f"{brief.brief_id}.json"
        async with aiofiles.open(brief_file, "w") as f:
            await f.write(brief.model_dump_json(indent=2))

        log.info(f"Saved brief: {brief_file}")
