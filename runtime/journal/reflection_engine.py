"""
NCL Journal Reflection Engine
==============================

Generates daily reflections by synthesizing journal entries with
intelligence briefs and working context. Uses LLM to detect patterns,
extract lessons, and build research queues for the next day.

Runs as part of the autonomous scheduler at 10pm ET.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from .models import DailyReflection, JournalInsight, TipEntry
from .store import local_today_str

log = logging.getLogger("ncl.journal.reflection")


class ReflectionEngine:
    """Synthesizes daily journal + intel into reflections and insights."""

    def __init__(self, journal_store, llm_client=None):
        """
        Args:
            journal_store: JournalStore instance
            llm_client: Async LLM client with a `generate(prompt, system)` method.
                         Falls back to template-based reflection if None.
        """
        self.journal = journal_store
        self.llm = llm_client

    async def generate_daily_reflection(
        self,
        intel_brief: dict | None = None,
        working_context: dict | None = None,
    ) -> DailyReflection:
        """
        Generate end-of-day reflection synthesizing journal + intel + context.

        Called by scheduler at 10pm ET.
        """
        # Date the reflection is FOR — must be the operator-local date (ET),
        # not UTC. At 10pm ET (= 02:00 UTC next day) UTC has already rolled
        # past midnight, but the journaling day is still the current ET day.
        today = local_today_str()

        # Check if already generated today
        existing = await self.journal.get_reflection(today)
        if existing:
            log.info(f"Reflection already exists for {today} — skipping")
            return existing

        # Gather today's entries
        entries = await self.journal.get_today_entries()

        # Gather recent tips for context
        tips = await self.journal.get_tips(limit=10)

        # Build reflection
        if self.llm and entries:
            reflection = await self._llm_reflection(today, entries, intel_brief, working_context)
        else:
            reflection = self._template_reflection(today, entries, intel_brief)

        # Persist
        await self.journal.save_reflection(reflection)

        # Extract any new insights from patterns
        if len(entries) >= 3:
            await self._detect_insights(entries, reflection)

        # Auto-extract tips from technique/best_practice entries
        for entry in entries:
            if entry.entry_type.value in ("technique", "best_practice") and entry.content:
                await self.journal.create_tip(
                    title=entry.title or entry.content[:80],
                    content=entry.content,
                    category=entry.tags[0] if entry.tags else "general",
                    tags=entry.tags,
                    source=f"journal:{entry.entry_id}",
                )

        # Bridge reflection to memory store
        if self.journal.memory_store and reflection.summary:
            try:
                await self.journal.memory_store.create_unit(
                    content=f"[Daily Reflection {today}] {reflection.summary[:600]}",
                    source="journal_reflection",
                    importance=65.0,
                    tags=["journal", "reflection", "daily"] + reflection.sectors_touched[:3],
                )
            except Exception as e:
                log.warning(f"Failed to bridge reflection to memory: {e}")

        log.info(f"Daily reflection generated for {today}: "
                 f"{reflection.entries_count} entries, "
                 f"{len(reflection.patterns_noticed)} patterns, "
                 f"{len(reflection.research_queue)} research topics")

        return reflection

    async def _llm_reflection(
        self,
        today: str,
        entries: list,
        intel_brief: dict | None,
        working_context: dict | None,
    ) -> DailyReflection:
        """Generate reflection using LLM synthesis."""
        # Build context for LLM
        entries_text = "\n\n".join(
            f"[{e.entry_type.value}] {e.title}\n{e.content[:500]}\nTags: {', '.join(e.tags)}"
            for e in entries[:15]
        )

        intel_text = ""
        if intel_brief:
            intel_text = (
                f"\nINTELLIGENCE CONTEXT:\n"
                f"Executive Summary: {intel_brief.get('executive_summary', 'N/A')[:300]}\n"
                f"Risk Alerts: {', '.join(intel_brief.get('risk_alerts', [])[:3])}\n"
            )

        wc_text = ""
        if working_context:
            items = working_context.get("items", [])[:5]
            wc_text = "\nWORKING CONTEXT:\n" + "\n".join(
                f"- {item.get('title', 'N/A')}: {item.get('content', '')[:150]}"
                for item in items
            )

        prompt = f"""Synthesize today's journal entries into a daily reflection.

DATE: {today}

JOURNAL ENTRIES ({len(entries)} total):
{entries_text}
{intel_text}
{wc_text}

Generate a JSON response with these fields:
- "summary": 2-3 sentence synthesis of the day's thinking and observations
- "patterns_noticed": list of patterns or themes across entries (max 5)
- "questions_raised": open questions that emerged today (max 5)
- "research_queue": specific topics to research tomorrow (max 5)
- "decisions_made": any decisions documented today (max 5)
- "lessons_learned": lessons or insights from today (max 5)
- "tomorrow_focus": suggested focus areas for tomorrow (max 3)

Be concise and actionable. Focus on what matters for decision-making."""

        try:
            response = await self.llm.generate(
                prompt=prompt,
                system="You are NATRIX's journal reflection engine. Synthesize daily entries into actionable insights. Return valid JSON only.",
            )

            # Parse LLM response
            data = self._parse_json_response(response)

            return DailyReflection(
                date=today,
                summary=data.get("summary", ""),
                patterns_noticed=data.get("patterns_noticed", [])[:5],
                questions_raised=data.get("questions_raised", [])[:5],
                research_queue=data.get("research_queue", [])[:5],
                decisions_made=data.get("decisions_made", [])[:5],
                lessons_learned=data.get("lessons_learned", [])[:5],
                open_questions=data.get("questions_raised", [])[:5],
                tomorrow_focus=data.get("tomorrow_focus", [])[:3],
                entries_count=len(entries),
                signals_referenced=sum(len(e.related_signals) for e in entries),
                sectors_touched=list(set(s for e in entries for s in e.linked_sectors))[:8],
            )

        except Exception as e:
            log.warning(f"LLM reflection failed, falling back to template: {e}")
            return self._template_reflection(today, entries, intel_brief)

    def _template_reflection(
        self,
        today: str,
        entries: list,
        intel_brief: dict | None = None,
    ) -> DailyReflection:
        """Fallback template-based reflection when LLM is unavailable."""
        # Extract by type
        decisions = [e for e in entries if e.entry_type.value == "decision"]
        questions = [e for e in entries if e.entry_type.value == "question"]
        lessons = [e for e in entries if e.entry_type.value == "lesson"]
        observations = [e for e in entries if e.entry_type.value == "observation"]

        # Build summary
        summary_parts = [f"Recorded {len(entries)} journal entries today."]
        if decisions:
            summary_parts.append(f"{len(decisions)} decisions documented.")
        if observations:
            summary_parts.append(f"{len(observations)} observations noted.")
        if questions:
            summary_parts.append(f"{len(questions)} open questions raised.")

        # Collect all tags as proxy for topics
        all_tags = [t for e in entries for t in e.tags]
        tag_counts = {}
        for t in all_tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(tag_counts, key=lambda x: -tag_counts[x])[:5]

        return DailyReflection(
            date=today,
            summary=" ".join(summary_parts),
            patterns_noticed=[f"Recurring topic: {t}" for t in top_tags[:3]],
            questions_raised=[q.title or q.content[:120] for q in questions[:5]],
            research_queue=[e.content[:120] for e in entries if e.research_topics][:5],
            decisions_made=[d.title or d.content[:120] for d in decisions[:5]],
            lessons_learned=[l.title or l.content[:120] for l in lessons[:5]],
            open_questions=[q.title or q.content[:120] for q in questions[:5]],
            tomorrow_focus=top_tags[:3],
            entries_count=len(entries),
            signals_referenced=sum(len(e.related_signals) for e in entries),
            sectors_touched=list(set(s for e in entries for s in e.linked_sectors))[:8],
        )

    async def _detect_insights(self, entries: list, reflection: DailyReflection) -> None:
        """Detect cross-entry patterns and persist as insights."""
        # Simple tag co-occurrence detection
        tag_pairs: dict[tuple, int] = {}
        for e in entries:
            tags = sorted(set(e.tags))
            for i, t1 in enumerate(tags):
                for t2 in tags[i + 1:]:
                    pair = (t1, t2)
                    tag_pairs[pair] = tag_pairs.get(pair, 0) + 1

        # Flag pairs appearing 3+ times
        for pair, count in tag_pairs.items():
            if count >= 3:
                insight = JournalInsight(
                    pattern=f"Recurring co-occurrence: {pair[0]} + {pair[1]} ({count} entries)",
                    evidence=[e.entry_id for e in entries if pair[0] in e.tags and pair[1] in e.tags],
                    frequency=count,
                    confidence=min(0.9, 0.3 + count * 0.1),
                    actionable=count >= 5,
                    recommendation=f"Consider dedicated research into the intersection of {pair[0]} and {pair[1]}.",
                )
                await self.journal.save_insight(insight)

    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```"):
            # Remove markdown code fences
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
        return {}


class ContextAwareTips:
    """Generate context-aware tips based on current journal + intel state."""

    # Built-in tips organized by category
    BUILTIN_TIPS = {
        "research": [
            {
                "title": "Triangle Validation",
                "content": "Always validate signals from at least 3 independent sources before acting. "
                           "Cross-reference Polymarket probabilities with news sentiment and on-chain data.",
                "tags": ["research", "validation"],
            },
            {
                "title": "Contrarian Signal Detection",
                "content": "When all sources agree strongly (>90% consensus), look for contrarian signals. "
                           "Unanimous agreement often precedes reversals. Check prediction market odds vs actual outcomes.",
                "tags": ["research", "contrarian"],
            },
            {
                "title": "Time-Decay Your Sources",
                "content": "Weight recent signals higher but don't ignore 48-72h old data. "
                           "Many patterns only become visible with a 2-3 day lookback window.",
                "tags": ["research", "time-management"],
            },
        ],
        "trading": [
            {
                "title": "Options Flow as Leading Indicator",
                "content": "Unusual Whales dark pool prints >$1M and concentrated OI changes often precede "
                           "price moves by 24-48 hours. Track max pain divergence from current price.",
                "tags": ["trading", "options"],
            },
            {
                "title": "Sector Rotation Detection",
                "content": "Monitor the SignalCorrelator's sector direction changes. When 3+ sectors shift "
                           "direction within 24 hours, it often signals regime change.",
                "tags": ["trading", "sectors"],
            },
        ],
        "operations": [
            {
                "title": "Morning Routine Optimization",
                "content": "Review morning brief → check working context → scan council flags → "
                           "journal observations → set today's research focus. 15 minutes total.",
                "tags": ["operations", "routine"],
            },
            {
                "title": "Signal-to-Noise Calibration",
                "content": "If you're getting too many push alerts, raise the threshold from 80 to 85. "
                           "If you're missing things, lower to 75. Calibrate weekly based on hit rate.",
                "tags": ["operations", "calibration"],
            },
            {
                "title": "Journal as Feedback Loop",
                "content": "Every decision you journal becomes memory. Every question becomes a research topic. "
                           "Every observation shapes tomorrow's working context. The journal IS the feedback loop.",
                "tags": ["operations", "journal"],
            },
        ],
        "council": [
            {
                "title": "Council Deep-Dive Triggers",
                "content": "Auto-trigger a council when: (1) 3+ high-importance signals converge, "
                           "(2) prediction confidence drops below 0.4, or (3) you're about to make a "
                           "major allocation decision. Let the models debate before you decide.",
                "tags": ["council", "triggers"],
            },
        ],
    }

    def __init__(self, journal_store):
        self.journal = journal_store

    async def get_contextual_tips(self, limit: int = 5) -> list[dict]:
        """Get tips relevant to current journal context and recent activity."""
        today_entries = await self.journal.get_today_entries()
        stored_tips = await self.journal.get_tips(limit=50)

        # Collect today's tags to find relevant categories
        today_tags = set()
        for e in today_entries:
            today_tags.update(e.tags)

        results = []

        # First: stored tips matching today's tags
        for tip in stored_tips:
            if any(t in today_tags for t in tip.tags):
                results.append({
                    "source": "personal",
                    "title": tip.title,
                    "content": tip.content,
                    "category": tip.category,
                    "relevance": "matches today's topics",
                })
                if len(results) >= limit:
                    return results

        # Second: builtin tips matching context
        for category, tips in self.BUILTIN_TIPS.items():
            if any(category in t for t in today_tags) or not today_tags:
                for tip in tips:
                    if any(t in today_tags for t in tip["tags"]) or not today_tags:
                        results.append({
                            "source": "builtin",
                            "title": tip["title"],
                            "content": tip["content"],
                            "category": category,
                            "relevance": "general best practice",
                        })
                        if len(results) >= limit:
                            return results

        # Fill remaining with random builtins
        if len(results) < limit:
            for category, tips in self.BUILTIN_TIPS.items():
                for tip in tips:
                    entry = {
                        "source": "builtin",
                        "title": tip["title"],
                        "content": tip["content"],
                        "category": category,
                        "relevance": "general",
                    }
                    if entry not in results:
                        results.append(entry)
                        if len(results) >= limit:
                            return results

        return results
