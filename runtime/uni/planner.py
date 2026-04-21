"""Research Planning Engine for UNI Cortex.

Decomposes research queries into sub-questions, identifies source strategies,
and creates execution plans with time estimates.
"""

import logging
from typing import Any

from .models import ResearchDepth, SourceType

log = logging.getLogger("uni.planner")


class ResearchPlanner:
    """Plans research strategy for complex queries."""

    def __init__(self):
        """Initialize research planner."""
        pass

    def plan_research(
        self,
        query: str,
        depth: ResearchDepth,
        sources_requested: list[SourceType],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a research execution plan for a query.

        Args:
            query: Research query to plan
            depth: Research depth level
            sources_requested: Preferred source types
            context: Optional context data

        Returns:
            dict with keys:
              - sub_questions: list[str]
              - source_strategy: dict mapping sub-questions to source types
              - execution_steps: list of ordered execution steps
              - estimated_duration_minutes: int
        """
        context = context or {}

        # Decompose query into sub-questions
        sub_questions = self._decompose_query(query, depth)

        # Determine source strategy
        source_strategy = self._determine_source_strategy(
            sub_questions, sources_requested
        )

        # Create execution plan
        execution_steps = self._create_execution_steps(
            sub_questions, source_strategy, depth
        )

        # Estimate duration based on depth
        estimated_duration = self._estimate_duration(depth, len(sub_questions))

        return {
            "sub_questions": sub_questions,
            "source_strategy": source_strategy,
            "execution_steps": execution_steps,
            "estimated_duration_minutes": estimated_duration,
        }

    def _decompose_query(self, query: str, depth: ResearchDepth) -> list[str]:
        """
        Decompose query into sub-questions.

        Rule-based decomposition:
        - Splits on logical connectors (and, or, also)
        - Adds contextual sub-questions (risks, alternatives, implications)
        - Depth determines count:
          * QUICK: 2 sub-questions
          * STANDARD: 4 sub-questions
          * DEEP: 6 sub-questions
          * EXHAUSTIVE: 8 sub-questions
        """
        # Start with the main query
        sub_questions = [query]

        # Split on logical connectors
        parts = self._split_on_connectors(query)
        if len(parts) > 1:
            sub_questions.extend(parts[1:])  # Add split parts

        # Add contextual sub-questions based on depth
        contextual_questions = self._generate_contextual_questions(query, depth)
        sub_questions.extend(contextual_questions)

        # Target count based on depth
        target_count = {
            ResearchDepth.QUICK: 2,
            ResearchDepth.STANDARD: 4,
            ResearchDepth.DEEP: 6,
            ResearchDepth.EXHAUSTIVE: 8,
        }.get(depth, 4)

        # Limit to target count
        if len(sub_questions) > target_count:
            sub_questions = sub_questions[:target_count]
        elif len(sub_questions) < target_count:
            # Add derived questions if needed
            sub_questions.extend(
                self._generate_derived_questions(query, target_count - len(sub_questions))
            )

        return list(dict.fromkeys(sub_questions))  # Remove duplicates, preserve order

    def _split_on_connectors(self, query: str) -> list[str]:
        """Split query on logical connectors (and, or, also)."""
        import re

        # Split on 'and', 'or', 'also' (case-insensitive, as whole words)
        parts = re.split(r"\s+(?:and|or|also)\s+", query, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    def _generate_contextual_questions(self, query: str, depth: ResearchDepth) -> list[str]:
        """Generate contextual sub-questions based on main query."""
        questions = []

        # Identify key terms in query
        key_terms = self._extract_key_terms(query)

        # Generate variations
        for term in key_terms[:2]:  # Focus on 2 main terms
            if "what" in query.lower():
                questions.append(f"What are the implications of {term}?")
                questions.append(f"What are the risks or limitations of {term}?")
            elif "how" in query.lower():
                questions.append(f"How is {term} currently implemented?")
                questions.append(f"What are the challenges in {term}?")
            elif "why" in query.lower():
                questions.append(f"What are the root causes of {term}?")
                questions.append(f"What are alternative explanations for {term}?")

        if depth in (ResearchDepth.DEEP, ResearchDepth.EXHAUSTIVE):
            questions.append(f"What are emerging trends in {key_terms[0]}?")
            questions.append(f"Who are the key players or experts in {key_terms[0]}?")

        return questions

    def _generate_derived_questions(self, query: str, count: int) -> list[str]:
        """Generate derived follow-up questions."""
        questions = []

        candidates = [
            f"What are the current state-of-the-art approaches to {query.split()[0]}?",
            f"How does {query.split()[0]} compare to alternatives?",
            f"What is the historical context of {query.split()[0]}?",
            f"What are the latest developments in {query.split()[0]}?",
            f"What are expert opinions on {query.split()[0]}?",
        ]

        for candidate in candidates[: min(count, len(candidates))]:
            questions.append(candidate)

        return questions

    def _extract_key_terms(self, query: str) -> list[str]:
        """Extract key nouns/terms from query."""
        import re

        # Simple heuristic: extract capitalized words or technical terms
        words = query.split()
        key_terms = [
            w for w in words if len(w) > 3 and w[0].isupper() or any(c.isdigit() for c in w)
        ]

        if not key_terms:
            # Fall back to longer words
            key_terms = [w for w in words if len(w) > 5]

        return key_terms[:3]  # Top 3

    def _determine_source_strategy(
        self,
        sub_questions: list[str],
        sources_requested: list[SourceType],
    ) -> dict[str, list[SourceType]]:
        """
        Map each sub-question to optimal source types.

        Heuristics:
        - "academic", "research", "study" → ACADEMIC
        - "news", "current", "latest" → NEWS
        - "market", "financial", "business" → MARKET_DATA
        - General questions → WEB
        - "internal", "memory", "history" → INTERNAL
        - "discuss", "opinion", "social" → SOCIAL
        """
        strategy = {}

        for question in sub_questions:
            q_lower = question.lower()
            assigned_sources = []

            # Check for source type indicators
            if any(term in q_lower for term in ["academic", "research", "study", "peer"]):
                assigned_sources.append(SourceType.ACADEMIC)
            if any(term in q_lower for term in ["news", "current", "latest", "today"]):
                assigned_sources.append(SourceType.NEWS)
            if any(
                term in q_lower
                for term in ["market", "financial", "business", "investment", "price"]
            ):
                assigned_sources.append(SourceType.MARKET_DATA)
            if any(term in q_lower for term in ["internal", "memory", "history", "past"]):
                assigned_sources.append(SourceType.INTERNAL)
            if any(term in q_lower for term in ["discuss", "opinion", "debate", "community"]):
                assigned_sources.append(SourceType.SOCIAL)

            # Fall back to requested sources
            if not assigned_sources:
                assigned_sources = sources_requested or [SourceType.WEB]

            # Ensure WEB is in the mix if sources are limited
            if not assigned_sources:
                assigned_sources = [SourceType.WEB]

            strategy[question] = assigned_sources

        return strategy

    def _create_execution_steps(
        self,
        sub_questions: list[str],
        source_strategy: dict[str, list[SourceType]],
        depth: ResearchDepth,
    ) -> list[dict[str, Any]]:
        """Create ordered execution steps."""
        steps = []

        # Step 1: Gather initial sources
        for i, question in enumerate(sub_questions, 1):
            sources = source_strategy.get(question, [SourceType.WEB])
            steps.append(
                {
                    "step_number": i,
                    "action": "gather",
                    "sub_question": question,
                    "source_types": sources,
                    "estimated_duration_seconds": 30,  # Per source type
                }
            )

        # Step 2: Analysis phase (happens after all gathering)
        steps.append(
            {
                "step_number": len(steps) + 1,
                "action": "analyze",
                "description": "Extract findings and identify contradictions",
                "estimated_duration_seconds": 60,
            }
        )

        # Step 3: Synthesis phase
        steps.append(
            {
                "step_number": len(steps) + 1,
                "action": "synthesize",
                "description": "Create consensus narrative and key takeaways",
                "estimated_duration_seconds": 45,
            }
        )

        return steps

    def _estimate_duration(self, depth: ResearchDepth, num_questions: int) -> int:
        """Estimate total research duration in minutes."""
        # Base time per depth level
        base_times = {
            ResearchDepth.QUICK: 5,
            ResearchDepth.STANDARD: 20,
            ResearchDepth.DEEP: 45,
            ResearchDepth.EXHAUSTIVE: 90,
        }

        base = base_times.get(depth, 20)

        # Add time per sub-question (30 seconds per question)
        additional = (num_questions * 30) // 60

        return base + additional
