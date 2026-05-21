"""Research Synthesis Engine for UNI Cortex.

Analyzes sources, extracts findings, identifies contradictions,
and produces synthesis narratives with recommendations.
"""

import json
import logging
import os
from typing import Any, Optional

import httpx

from .models import Finding, ResearchBrief, ResearchResult, ResearchStatus, SourceResult

log = logging.getLogger("uni.synthesizer")


class ResearchSynthesizer:
    """Synthesizes research sources into findings and briefs."""

    def __init__(
        self,
        claude_api_key: Optional[str] = None,
        xai_api_key: Optional[str] = None,
        anthropic_base_url: str = "https://api.anthropic.com",
        ollama_host: str = "localhost:11434",
    ):
        """
        Initialize research synthesizer.

        Args:
            claude_api_key: Anthropic API key
            xai_api_key: xAI API key
            anthropic_base_url: Anthropic API base URL
            ollama_host: Ollama server host:port
        """
        self.claude_api_key = claude_api_key
        self.xai_api_key = xai_api_key
        self.anthropic_base_url = anthropic_base_url
        self.ollama_host = ollama_host
        self.http_client = httpx.AsyncClient(timeout=90.0)

    async def close(self) -> None:
        """Close the underlying HTTP client to release connections."""
        if self.http_client and not self.http_client.is_closed:
            await self.http_client.aclose()

    async def synthesize(
        self,
        query: str,
        sources: list[SourceResult],
        context: dict[str, Any] | None = None,
    ) -> ResearchResult:
        """
        Synthesize sources into research findings and narrative.

        AI chain: Claude → Grok → Ollama fallback

        Args:
            query: Original research query
            sources: Gathered source results
            context: Optional context data

        Returns:
            ResearchResult with findings and synthesis
        """
        context = context or {}

        # Build synthesis prompt
        prompt = self._build_synthesis_prompt(query, sources, context)

        # Call AI with fallback chain
        try:
            synthesis_text = await self._call_claude(prompt)
            model_used = "claude"
        except Exception as e:
            log.warning(f"Claude synthesis failed: {e}, trying Grok")
            try:
                synthesis_text = await self._call_grok(prompt)
                model_used = "grok"
            except Exception as e2:
                log.warning(f"Grok synthesis failed: {e2}, trying Ollama")
                try:
                    synthesis_text = await self._call_ollama(prompt)
                    model_used = "ollama"
                except Exception as e3:
                    log.error(f"All AI models failed: {e3}")
                    synthesis_text = self._fallback_synthesis(query, sources)
                    model_used = "fallback"

        # Extract findings from synthesis
        findings = self._extract_findings(query, sources, synthesis_text)

        # Identify contradictions
        self._identify_contradictions(findings, sources)

        # Generate key takeaways
        key_takeaways = self._extract_key_takeaways(synthesis_text)

        # Calculate confidence score
        confidence_score = self._calculate_confidence(sources, findings)

        result = ResearchResult(
            task_id="",  # Will be set by cortex
            query=query,
            status=ResearchStatus.COMPLETE,
            findings=findings,
            synthesis=synthesis_text,
            key_takeaways=key_takeaways,
            sources_consulted=sources,
            confidence_score=confidence_score,
            model_used=model_used,
            research_plan={},  # Will be set by cortex
        )

        return result

    async def create_brief(self, result: ResearchResult) -> ResearchBrief:
        """
        Create an executive brief from research result.

        Args:
            result: ResearchResult to condense

        Returns:
            ResearchBrief with executive summary and recommendations
        """
        # Create executive summary (first sentence of synthesis or AI-generated)
        executive_summary = self._extract_summary(result.synthesis)

        # Condense findings to top 3-5
        condensed_findings = self._condense_findings(result.findings, max_count=5)

        # Generate recommendations from findings
        recommendations = self._generate_recommendations(
            result.key_takeaways, condensed_findings
        )

        # Identify risk factors
        risk_factors = self._identify_risks(condensed_findings, result.sources_consulted)

        brief = ResearchBrief(
            title=f"Research Brief: {result.query[:50]}",
            executive_summary=executive_summary,
            findings=condensed_findings,
            recommendations=recommendations,
            risk_factors=risk_factors,
            confidence=result.confidence_score,
            sources_count=len(result.sources_consulted),
        )

        return brief

    def _build_synthesis_prompt(
        self, query: str, sources: list[SourceResult], context: dict[str, Any]
    ) -> str:
        """Build synthesis prompt for AI model."""

        # Summarize sources
        sources_text = ""
        for i, src in enumerate(sources, 1):
            sources_text += f"\n[Source {i}] {src.title}\n"
            sources_text += f"  Type: {src.source_type.value}\n"
            sources_text += f"  Relevance: {src.relevance_score:.1%}\n"
            sources_text += f"  Credibility: {src.credibility_score:.1%}\n"
            sources_text += f"  Content: {src.content[:300]}\n"

        prompt = f"""You are a research analyst synthesizing findings from multiple sources.

RESEARCH QUERY: {query}

SOURCES REVIEWED:
{sources_text}

YOUR TASK:
1. Analyze the sources and identify key findings
2. Note any contradictions or conflicting claims
3. Assess the overall credibility and confidence level
4. Provide a clear synthesis narrative
5. List the 3-5 most important takeaways
6. Flag any uncertainties or knowledge gaps

OUTPUT FORMAT:
SYNTHESIS NARRATIVE:
[Write 2-3 paragraphs synthesizing the sources into a coherent narrative]

KEY FINDINGS:
- [Finding 1]
- [Finding 2]
- [Finding 3]
[... up to 5 findings]

KEY TAKEAWAYS:
- [Takeaway 1]
- [Takeaway 2]
- [Takeaway 3]

CONFIDENCE LEVEL: [0-100]

CONTRADICTIONS:
[List any contradictions between sources, or "None identified"]

KNOWLEDGE GAPS:
[List areas that need further research, or "Comprehensive coverage"]
"""
        return prompt

    async def _call_claude(self, prompt: str) -> str:
        """Call Claude API for synthesis."""
        if not self.claude_api_key:
            raise ValueError("Claude API key not configured")

        resp = await self.http_client.post(
            f"{self.anthropic_base_url}/v1/messages",
            headers={
                "x-api-key": self.claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if not content or not isinstance(content, list):
            raise ValueError(f"Unexpected Claude response: {list(data.keys())}")

        # Track cost
        try:
            from ..cost_tracker import record_cost
            usage = data.get("usage", {})
            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            cost_usd = (input_t * 3.0 + output_t * 15.0) / 1_000_000
            await record_cost("anthropic", cost_usd, "uni_synthesis",
                              f"claude synthesis in={input_t} out={output_t}")
        except Exception:
            pass

        return content[0].get("text", "")

    async def _call_grok(self, prompt: str) -> str:
        """Call Grok API for synthesis."""
        if not self.xai_api_key:
            raise ValueError("Grok API key not configured")

        resp = await self.http_client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.xai_api_key}"},
            json={
                "model": "grok-3",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.6,
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"Grok returned no choices: {list(data.keys())}")

        # Track cost
        try:
            from ..cost_tracker import record_cost
            usage = data.get("usage", {})
            input_t = usage.get("prompt_tokens", 0)
            output_t = usage.get("completion_tokens", 0)
            cost_usd = (input_t * 2.0 + output_t * 10.0) / 1_000_000
            await record_cost("xai", cost_usd, "uni_synthesis",
                              f"grok-3 synthesis in={input_t} out={output_t}")
        except Exception:
            pass

        return choices[0].get("message", {}).get("content", "")

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama local model for synthesis."""
        resp = await self.http_client.post(
            f"http://{self.ollama_host}/api/generate",
            json={
                "model": "qwen3:32b",
                "prompt": prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _fallback_synthesis(
        self, query: str, sources: list[SourceResult]
    ) -> str:
        """Generate fallback synthesis when all AI models fail."""
        text = f"Research synthesis for: {query}\n\n"
        text += f"Sources analyzed: {len(sources)}\n"

        avg_relevance = sum(s.relevance_score for s in sources) / len(sources) if sources else 0
        avg_credibility = (
            sum(s.credibility_score for s in sources) / len(sources) if sources else 0
        )

        text += f"Average relevance: {avg_relevance:.1%}\n"
        text += f"Average credibility: {avg_credibility:.1%}\n\n"

        text += "Key sources:\n"
        for i, src in enumerate(sources[:3], 1):
            text += f"{i}. {src.title} ({src.source_type.value})\n"

        return text

    def _extract_findings(
        self, query: str, sources: list[SourceResult], synthesis: str
    ) -> list[Finding]:
        """Extract structured findings from synthesis."""
        findings = []

        # Parse synthesis for findings section
        if "KEY FINDINGS:" in synthesis:
            findings_text = synthesis.split("KEY FINDINGS:")[1].split("\n\n")[0]
            lines = [l.strip().lstrip("-").strip() for l in findings_text.split("\n") if l.strip()]

            for line in lines:
                if line:
                    finding = Finding(
                        claim=line,
                        evidence=[src.title for src in sources[:2]],
                        confidence=0.7,
                        sources=[src.source_id for src in sources[:2]],
                    )
                    findings.append(finding)

        return findings

    def _identify_contradictions(self, findings: list[Finding], sources: list[SourceResult]):
        """Identify contradictions between sources."""
        # Simplified: mark if sources have conflicting claims
        for finding in findings:
            if len(sources) > 1:
                # Check if different sources have different slants
                credibilities = [s.credibility_score for s in sources]
                if max(credibilities) - min(credibilities) > 0.3:
                    finding.contradictions.append(
                        "Sources vary in credibility or may present conflicting information"
                    )

    def _extract_key_takeaways(self, synthesis: str) -> list[str]:
        """Extract key takeaways from synthesis text."""
        takeaways = []

        if "KEY TAKEAWAYS:" in synthesis:
            takeaways_text = synthesis.split("KEY TAKEAWAYS:")[1].split("\n\n")[0]
            lines = [l.strip().lstrip("-").strip() for l in takeaways_text.split("\n") if l.strip()]
            takeaways = lines[:5]

        return takeaways

    def _calculate_confidence(
        self, sources: list[SourceResult], findings: list[Finding]
    ) -> float:
        """Calculate overall confidence score."""
        if not sources:
            return 0.0

        # Average credibility and relevance
        avg_credibility = sum(s.credibility_score for s in sources) / len(sources)
        avg_relevance = sum(s.relevance_score for s in sources) / len(sources)

        # Average finding confidence
        avg_finding_confidence = (
            sum(f.confidence for f in findings) / len(findings) if findings else 0.5
        )

        # Weighted average
        confidence = (avg_credibility * 0.4) + (avg_relevance * 0.3) + (avg_finding_confidence * 0.3)
        return min(1.0, max(0.0, confidence))

    def _extract_summary(self, synthesis: str) -> str:
        """Extract executive summary from synthesis."""
        lines = synthesis.split("\n")
        for line in lines:
            if line.strip() and not line.startswith("["):
                return line.strip()[:200]
        return "Research synthesis completed."

    def _condense_findings(self, findings: list[Finding], max_count: int = 5) -> list[Finding]:
        """Keep only the most important findings."""
        # Sort by confidence score
        sorted_findings = sorted(findings, key=lambda f: f.confidence, reverse=True)
        return sorted_findings[:max_count]

    def _generate_recommendations(
        self, takeaways: list[str], findings: list[Finding]
    ) -> list[str]:
        """Generate recommendations from findings."""
        recommendations = []

        for takeaway in takeaways[:3]:
            rec = f"Based on '{takeaway[:50]}...': {takeaway}"
            recommendations.append(rec)

        return recommendations

    def _identify_risks(
        self, findings: list[Finding], sources: list[SourceResult]
    ) -> list[str]:
        """Identify risk factors from findings."""
        risks = []

        # Flag findings with low confidence as risks
        for finding in findings:
            if finding.confidence < 0.6:
                risks.append(f"Uncertain: {finding.claim} (confidence: {finding.confidence:.0%})")

        # Flag if credibility varies significantly
        if sources:
            credibilities = [s.credibility_score for s in sources]
            if max(credibilities) - min(credibilities) > 0.3:
                risks.append("Source credibility varies significantly — corroborate findings")

        return risks[:5]
