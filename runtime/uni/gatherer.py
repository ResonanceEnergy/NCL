"""Source Gathering Engine for UNI Cortex.

Collects research sources from multiple types: web, academic, news, social,
internal memory, market data. Mock-friendly design for testing.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

import aiofiles
import httpx

from .models import SourceResult, SourceType

log = logging.getLogger("uni.gatherer")


class ResearchGatherer:
    """Gathers sources from multiple source types."""

    def __init__(
        self,
        data_dir: str | Path,
        claude_api_key: Optional[str] = None,
        xai_api_key: Optional[str] = None,
        ollama_host: str = "localhost:11434",
    ):
        """
        Initialize research gatherer.

        Args:
            data_dir: Data directory for memory/internal sources
            claude_api_key: Anthropic API key (for structured research)
            xai_api_key: xAI API key (fallback)
            ollama_host: Ollama server host:port
        """
        self.data_dir = Path(data_dir).expanduser()
        self.claude_api_key = claude_api_key
        self.xai_api_key = xai_api_key
        self.ollama_host = ollama_host
        self.http_client = httpx.AsyncClient(timeout=60.0)

    async def gather_sources(
        self,
        sub_question: str,
        source_types: list[SourceType],
        max_per_type: int = 3,
    ) -> list[SourceResult]:
        """
        Gather sources for a sub-question from specified source types.

        Args:
            sub_question: Sub-question to research
            source_types: List of source types to prioritize
            max_per_type: Max sources per type

        Returns:
            List of SourceResult objects
        """
        results = []

        for source_type in source_types:
            try:
                if source_type == SourceType.WEB:
                    sources = await self._gather_web(sub_question, max_per_type)
                elif source_type == SourceType.ACADEMIC:
                    sources = await self._gather_academic(sub_question, max_per_type)
                elif source_type == SourceType.NEWS:
                    sources = await self._gather_news(sub_question, max_per_type)
                elif source_type == SourceType.SOCIAL:
                    sources = await self._gather_social(sub_question, max_per_type)
                elif source_type == SourceType.INTERNAL:
                    sources = await self._gather_internal(sub_question, max_per_type)
                elif source_type == SourceType.MARKET_DATA:
                    sources = await self._gather_market(sub_question, max_per_type)
                else:
                    sources = []

                results.extend(sources)
                log.info(
                    f"Gathered {len(sources)} sources from {source_type.value} for: {sub_question[:50]}"
                )

            except Exception as e:
                log.warning(
                    f"Failed to gather {source_type.value} sources: {e}",
                    exc_info=True,
                )
                # Graceful fallback — continue with other source types

        return results

    async def gather_all(
        self, plan: dict[str, Any]
    ) -> list[SourceResult]:
        """
        Execute full gathering plan, running all sub-questions in parallel.

        Args:
            plan: Research plan from planner with sub_questions and source_strategy

        Returns:
            All gathered sources
        """
        sub_questions = plan.get("sub_questions", [])
        source_strategy = plan.get("source_strategy", {})

        # Create gather tasks for all sub-questions
        tasks = []
        for question in sub_questions:
            source_types = source_strategy.get(question, [SourceType.WEB])
            task = self.gather_sources(question, source_types)
            tasks.append(task)

        # Run all in parallel
        all_results = await asyncio.gather(*tasks, return_exceptions=False)

        # Flatten results
        sources = []
        for result_list in all_results:
            sources.extend(result_list)

        log.info(f"Completed gathering phase: {len(sources)} sources collected")
        return sources

    async def _llm_research(self, prompt: str, model: str = "claude") -> str:
        """
        Call LLM for research synthesis. Falls back through Claude → Grok → Ollama.

        Follows Paperclip/MWP cost tracking: each call is a research operation
        logged through the UNI agent budget.
        """
        # Try Claude first (Perplexity-style research prompt)
        if model == "claude" and self.claude_api_key:
            try:
                resp = await self.http_client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.claude_api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 1024,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
            except Exception as e:
                log.warning(f"Claude research failed, trying Grok: {e}")

        # Try Grok
        if self.xai_api_key:
            try:
                resp = await self.http_client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.xai_api_key}"},
                    json={
                        "model": "grok-3-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1024,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                log.warning(f"Grok research failed, trying Ollama: {e}")

        # Fallback to Ollama
        try:
            resp = await self.http_client.post(
                f"http://{self.ollama_host}/api/generate",
                json={"model": "qwen3:32b", "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as e:
            log.error(f"All LLM research calls failed: {e}")
            return ""

    def _parse_research_results(
        self, text: str, source_type: SourceType, query: str, max_results: int
    ) -> list[SourceResult]:
        """Parse LLM research output into SourceResult objects."""
        results = []
        if not text:
            return results

        # Split response into logical sections (numbered items or paragraphs)
        sections = []
        current = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if current:
                    sections.append("\n".join(current))
                    current = []
            else:
                current.append(stripped)
        if current:
            sections.append("\n".join(current))

        for i, section in enumerate(sections[:max_results]):
            # Extract title (first line or first sentence)
            lines = section.split("\n")
            title = lines[0][:200].strip("# -•*0123456789.)")
            content = section[:1000]

            # Extract URLs if present
            url = None
            import re
            url_match = re.search(r'https?://[^\s\)\]]+', section)
            if url_match:
                url = url_match.group(0)

            # Score based on position and content length
            relevance = max(0.4, min(0.95, 0.8 - (i * 0.05)))
            credibility_map = {
                SourceType.WEB: 0.65,
                SourceType.ACADEMIC: 0.85,
                SourceType.NEWS: 0.70,
                SourceType.SOCIAL: 0.50,
                SourceType.MARKET_DATA: 0.80,
                SourceType.INTERNAL: 0.90,
            }

            result = SourceResult(
                source_type=source_type,
                url=url,
                title=title if title else f"Research on {query[:50]}",
                content=content,
                relevance_score=relevance,
                credibility_score=credibility_map.get(source_type, 0.6),
            )
            results.append(result)

        return results

    async def _gather_web(
        self, query: str, max_results: int = 3
    ) -> list[SourceResult]:
        """
        Gather web sources using LLM-powered research synthesis.

        Uses Claude/Grok/Ollama to generate grounded research with real
        references where possible. Follows MWP research-pipeline conventions.
        """
        prompt = (
            f"Research the following topic and provide {max_results} distinct findings "
            f"with sources where available. For each finding, include: a title, "
            f"key content/evidence, and source URL if known.\n\n"
            f"Topic: {query}\n\n"
            f"Format each finding as a numbered item with title, content, and source."
        )
        text = await self._llm_research(prompt)
        return self._parse_research_results(text, SourceType.WEB, query, max_results)

    async def _gather_academic(
        self, query: str, max_results: int = 3
    ) -> list[SourceResult]:
        """Gather academic sources using LLM-powered scholarly research."""
        prompt = (
            f"Provide {max_results} relevant academic or peer-reviewed research findings "
            f"on: {query}\n\n"
            f"For each, provide: paper title, key findings, authors if known, "
            f"and DOI or URL if available. Focus on well-cited, reputable research."
        )
        text = await self._llm_research(prompt)
        return self._parse_research_results(text, SourceType.ACADEMIC, query, max_results)

    async def _gather_news(
        self, query: str, max_results: int = 3
    ) -> list[SourceResult]:
        """Gather news sources using LLM-powered current events research."""
        prompt = (
            f"Provide {max_results} recent news developments related to: {query}\n\n"
            f"For each, include: headline, key details, source publication, "
            f"and approximate date. Focus on the most recent and impactful coverage."
        )
        text = await self._llm_research(prompt)
        return self._parse_research_results(text, SourceType.NEWS, query, max_results)

    async def _gather_social(
        self, query: str, max_results: int = 3
    ) -> list[SourceResult]:
        """Gather social media and community discussion insights."""
        prompt = (
            f"Summarize {max_results} notable community discussions, forum threads, "
            f"or social media conversations about: {query}\n\n"
            f"Include: discussion topic, key viewpoints, community sentiment, "
            f"and platform/source. Focus on substantive discussions, not noise."
        )
        text = await self._llm_research(prompt)
        return self._parse_research_results(text, SourceType.SOCIAL, query, max_results)

    async def _gather_internal(
        self, query: str, max_results: int = 3
    ) -> list[SourceResult]:
        """
        Gather from internal NCL memory, event history, and past research.

        Queries the actual memory store and events.ndjson for relevant
        prior knowledge, following MWP memory-processing conventions.
        """
        results = []

        # Search NCL memory store
        memory_file = self.data_dir / "memory" / "units.jsonl"
        if memory_file.exists():
            try:
                query_lower = query.lower()
                query_words = set(query_lower.split())
                async with aiofiles.open(memory_file, "r") as f:
                    async for line in f:
                        if not line.strip():
                            continue
                        try:
                            unit = json.loads(line)
                            content = str(unit.get("content", "")).lower()
                            tags = [t.lower() for t in unit.get("tags", [])]
                            # Match on content keywords or tag overlap
                            content_words = set(content.split())
                            overlap = len(query_words & content_words)
                            tag_overlap = len(query_words & set(tags))
                            if overlap >= 2 or tag_overlap >= 1:
                                relevance = min(0.95, 0.5 + (overlap * 0.1) + (tag_overlap * 0.15))
                                result = SourceResult(
                                    source_type=SourceType.INTERNAL,
                                    url=None,
                                    title=f"Memory: {str(unit.get('content', ''))[:80]}",
                                    content=str(unit.get("content", ""))[:1000],
                                    relevance_score=relevance,
                                    credibility_score=0.90,
                                )
                                results.append(result)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                log.warning(f"Failed to search internal memory: {e}")

        # Search events log
        events_file = self.data_dir / "events.ndjson"
        if events_file.exists() and len(results) < max_results:
            try:
                query_lower = query.lower()
                async with aiofiles.open(events_file, "r") as f:
                    async for line in f:
                        if len(results) >= max_results:
                            break
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                            desc = str(event.get("description", "")).lower()
                            if any(w in desc for w in query_lower.split() if len(w) > 3):
                                result = SourceResult(
                                    source_type=SourceType.INTERNAL,
                                    url=None,
                                    title=f"Event: {event.get('type', 'unknown')}",
                                    content=str(event.get("description", ""))[:500],
                                    relevance_score=0.65,
                                    credibility_score=0.95,
                                )
                                results.append(result)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                log.warning(f"Failed to search events: {e}")

        # Sort by relevance and limit
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:max_results]

    async def _gather_market(
        self, query: str, max_results: int = 3
    ) -> list[SourceResult]:
        """
        Gather market research and financial data.

        Queries AAC War Room data if available, falls back to LLM synthesis.
        """
        results = []

        # Try AAC endpoints for live market data
        try:
            resp = await self.http_client.get(
                "http://localhost:8080/health", timeout=3.0,
            )
            if resp.status_code < 400:
                # AAC is online — try to get market regime data
                try:
                    regime_resp = await self.http_client.get(
                        "http://localhost:8080/regime", timeout=5.0,
                    )
                    if regime_resp.status_code < 400:
                        data = regime_resp.json()
                        result = SourceResult(
                            source_type=SourceType.MARKET_DATA,
                            url="http://localhost:8080/regime",
                            title="AAC War Room: Current Market Regime",
                            content=json.dumps(data, indent=2)[:1000],
                            relevance_score=0.90,
                            credibility_score=0.95,
                        )
                        results.append(result)
                except Exception:
                    pass
        except Exception:
            pass

        # Fill remaining with LLM research
        if len(results) < max_results:
            prompt = (
                f"Provide {max_results - len(results)} market research insights on: {query}\n\n"
                f"Include: market data, trends, financial metrics, and analysis. "
                f"Focus on actionable intelligence with specific numbers where possible."
            )
            text = await self._llm_research(prompt)
            results.extend(
                self._parse_research_results(text, SourceType.MARKET_DATA, query, max_results - len(results))
            )

        return results[:max_results]
