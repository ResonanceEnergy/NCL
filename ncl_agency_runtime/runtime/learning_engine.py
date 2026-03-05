#!/usr/bin/env python3
"""
NCL Learning Engine - Pattern extraction and knowledge synthesis
"""

import json
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

try:
    from ncl_memory import search_memories, store_semantic_memory, get_memory_manager
    from memory_api import get_memory_api
    MEMORY_ENABLED = True
except ImportError:
    print("Warning: Memory system not available")
    MEMORY_ENABLED = False


class LearningEngine:
    """Engine for extracting patterns and synthesizing knowledge from memories"""

    def __init__(self):
        self.memory_api = get_memory_api() if MEMORY_ENABLED else None
        self.patterns = self._load_patterns()

    def _load_patterns(self) -> Dict:
        """Load pattern recognition templates"""
        return {
            "productivity_patterns": {
                "focus_sessions": {
                    "keywords": ["focus", "deep work", "concentration", "pomodoro"],
                    "indicators": ["duration", "quality", "interruptions"]
                },
                "task_completion": {
                    "keywords": ["completed", "finished", "done", "achieved"],
                    "indicators": ["time_taken", "difficulty", "satisfaction"]
                }
            },
            "behavior_patterns": {
                "energy_levels": {
                    "keywords": ["energy", "tired", "fatigue", "alert", "motivated"],
                    "indicators": ["time_of_day", "activities", "causes"]
                },
                "mood_patterns": {
                    "keywords": ["mood", "stress", "anxiety", "calm", "frustrated"],
                    "indicators": ["triggers", "duration", "coping_strategies"]
                }
            },
            "temporal_patterns": {
                "daily_rhythms": {
                    "keywords": ["morning", "afternoon", "evening", "night"],
                    "indicators": ["productivity", "energy", "activities"]
                },
                "weekly_cycles": {
                    "keywords": ["monday", "weekend", "weekday"],
                    "indicators": ["performance", "habits", "goals"]
                }
            }
        }

    def analyze_recent_events(self, days_back: int = 7) -> Dict:
        """Analyze recent events to extract patterns and insights"""
        if not MEMORY_ENABLED:
            return {"error": "Memory system not available"}

        # Get recent episodic memories
        query = {
            "memory_type": "episodic",
            "time_range": (datetime.now() - timedelta(days=days_back), datetime.now())
        }

        memories = search_memories(query, limit=500)
        events = [mem.content for mem in memories if isinstance(mem.content, dict)]

        analysis = {
            "period": f"Last {days_back} days",
            "total_events": len(events),
            "patterns": {},
            "insights": [],
            "recommendations": []
        }

        # Analyze event type distribution
        event_types = Counter()
        categories = Counter()

        for event in events:
            if "event_type" in event:
                event_types[event["event_type"]] += 1
            if "category" in event:
                categories[event["category"]] += 1

        analysis["patterns"]["event_types"] = dict(event_types.most_common(10))
        analysis["patterns"]["categories"] = dict(categories.most_common(5))

        # Extract productivity patterns
        productivity_insights = self._analyze_productivity_patterns(events)
        analysis["patterns"]["productivity"] = productivity_insights

        # Extract temporal patterns
        temporal_insights = self._analyze_temporal_patterns(events)
        analysis["patterns"]["temporal"] = temporal_insights

        # Generate insights and recommendations
        analysis["insights"] = self._generate_insights(analysis["patterns"])
        analysis["recommendations"] = self._generate_recommendations(analysis["patterns"])

        # Store learned knowledge
        self._store_learned_knowledge(analysis)

        return analysis

    def _analyze_productivity_patterns(self, events: List[Dict]) -> Dict:
        """Analyze productivity-related patterns"""
        focus_sessions = []
        task_completions = []

        for event in events:
            event_type = event.get("event_type", "").lower()

            # Focus sessions
            if any(keyword in event_type for keyword in ["focus", "deep", "work"]):
                focus_sessions.append(event)

            # Task completions
            if any(keyword in event_type for keyword in ["complete", "finish", "done"]):
                task_completions.append(event)

        patterns = {
            "focus_sessions": {
                "count": len(focus_sessions),
                "avg_duration": self._calculate_avg_duration(focus_sessions),
                "quality_distribution": self._analyze_quality(focus_sessions)
            },
            "task_completions": {
                "count": len(task_completions),
                "success_rate": len([t for t in task_completions if t.get("success", True)]) / max(len(task_completions), 1)
            }
        }

        return patterns

    def _analyze_temporal_patterns(self, events: List[Dict]) -> Dict:
        """Analyze temporal patterns in events"""
        hourly_distribution = defaultdict(int)
        daily_distribution = defaultdict(int)

        for event in events:
            occurred_at = event.get("occurred_at")
            if occurred_at:
                try:
                    dt = datetime.fromisoformat(occurred_at.replace('Z', '+00:00'))
                    hourly_distribution[dt.hour] += 1
                    daily_distribution[dt.weekday()] += 1  # 0=Monday, 6=Sunday
                except:
                    continue

        patterns = {
            "peak_hours": sorted(hourly_distribution.items(), key=lambda x: x[1], reverse=True)[:3],
            "active_days": sorted(daily_distribution.items(), key=lambda x: x[1], reverse=True)[:3],
            "weekday_vs_weekend": {
                "weekday_avg": sum(count for day, count in daily_distribution.items() if day < 5) / max(sum(1 for day in daily_distribution if day < 5), 1),
                "weekend_avg": sum(count for day, count in daily_distribution.items() if day >= 5) / max(sum(1 for day in daily_distribution if day >= 5), 1)
            }
        }

        return patterns

    def _generate_insights(self, patterns: Dict) -> List[str]:
        """Generate insights from patterns"""
        insights = []

        # Productivity insights
        prod = patterns.get("productivity", {})
        focus = prod.get("focus_sessions", {})

        if focus.get("count", 0) > 0:
            avg_duration = focus.get("avg_duration", 0)
            if avg_duration > 60:
                insights.append(f"Long focus sessions (avg {avg_duration:.1f} min) suggest good deep work capacity")
            elif avg_duration < 25:
                insights.append(f"Short focus sessions (avg {avg_duration:.1f} min) may indicate frequent interruptions")

        # Temporal insights
        temporal = patterns.get("temporal", {})
        peak_hours = temporal.get("peak_hours", [])

        if peak_hours:
            best_hour = peak_hours[0][0]
            insights.append(f"Most productive hour is {best_hour}:00, consider scheduling important tasks then")

        weekday_avg = temporal.get("weekday_vs_weekend", {}).get("weekday_avg", 0)
        weekend_avg = temporal.get("weekday_vs_weekend", {}).get("weekend_avg", 0)

        if weekend_avg > weekday_avg * 1.2:
            insights.append("Higher weekend activity suggests work-life balance opportunities")
        elif weekday_avg > weekend_avg * 1.2:
            insights.append("High weekday activity - consider weekend recovery time")

        return insights

    def _generate_recommendations(self, patterns: Dict) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []

        prod = patterns.get("productivity", {})
        focus = prod.get("focus_sessions", {})

        if focus.get("count", 0) < 5:
            recommendations.append("Increase focus session frequency to build better concentration habits")

        temporal = patterns.get("temporal", {})
        peak_hours = temporal.get("peak_hours", [])

        if peak_hours and len(peak_hours) > 1:
            recommendations.append(f"Schedule creative work during peak hours ({peak_hours[0][0]}:00) and routine tasks during secondary peaks")

        return recommendations

    def _store_learned_knowledge(self, analysis: Dict) -> None:
        """Store learned patterns as semantic memory"""
        if not MEMORY_ENABLED:
            return

        # Store key insights
        for insight in analysis.get("insights", []):
            store_semantic_memory(
                content={
                    "type": "behavioral_insight",
                    "insight": insight,
                    "analysis_period": analysis["period"],
                    "confidence": 0.8
                },
                tags=["insight", "behavior", "learned"],
                context={
                    "source": "learning_engine",
                    "analysis_type": "pattern_recognition"
                }
            )

        # Store productivity patterns
        prod_patterns = analysis.get("patterns", {}).get("productivity", {})
        if prod_patterns:
            store_semantic_memory(
                content={
                    "type": "productivity_pattern",
                    "patterns": prod_patterns,
                    "analysis_period": analysis["period"]
                },
                tags=["productivity", "pattern", "learned"],
                context={
                    "source": "learning_engine",
                    "pattern_type": "productivity"
                }
            )

    def learn_from_task_execution(self, task: Dict, result: Dict) -> None:
        """Learn from task execution patterns"""
        if not MEMORY_ENABLED:
            return

        # Analyze task success patterns
        success = result.get("success", False)
        task_type = task.get("type", "unknown")

        # Store task execution pattern
        pattern = {
            "task_type": task_type,
            "success": success,
            "duration": result.get("duration"),
            "factors": self._extract_success_factors(task, result)
        }

        store_semantic_memory(
            content=pattern,
            tags=["task_pattern", f"task:{task_type}", "execution"],
            context={
                "source": "task_learning",
                "success_rate": 1.0 if success else 0.0
            }
        )

    def _extract_success_factors(self, task: Dict, result: Dict) -> List[str]:
        """Extract factors that contributed to task success/failure"""
        factors = []

        if result.get("success"):
            factors.append("successful_execution")
        else:
            factors.append("failed_execution")

        # Add time-based factors
        duration = result.get("duration")
        if duration:
            if duration < 30:
                factors.append("quick_completion")
            elif duration > 120:
                factors.append("long_duration")

        return factors

    def _calculate_avg_duration(self, events: List[Dict]) -> float:
        """Calculate average duration from events"""
        durations = []
        for event in events:
            data = event.get("data", {})
            if "duration" in data:
                durations.append(data["duration"])

        return sum(durations) / max(len(durations), 1) if durations else 0

    def _analyze_quality(self, events: List[Dict]) -> Dict:
        """Analyze quality distribution"""
        qualities = []
        for event in events:
            data = event.get("data", {})
            if "quality" in data:
                qualities.append(data["quality"])

        return dict(Counter(qualities))


# Global learning engine instance
_learning_engine = None

def get_learning_engine() -> LearningEngine:
    """Get or create global learning engine instance"""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine

def analyze_recent_patterns(days_back: int = 7) -> Dict:
    """Convenience function for pattern analysis"""
    return get_learning_engine().analyze_recent_events(days_back)

def learn_from_task(task: Dict, result: Dict) -> None:
    """Convenience function for task learning"""
    get_learning_engine().learn_from_task_execution(task, result)


if __name__ == "__main__":
    # Example usage
    engine = get_learning_engine()

    # Analyze recent patterns
    analysis = engine.analyze_recent_events(days_back=7)
    print(f"Analysis complete: {analysis['total_events']} events analyzed")
    print(f"Insights: {len(analysis['insights'])}")
    print(f"Recommendations: {len(analysis['recommendations'])}")

    # Print some insights
    for insight in analysis.get("insights", [])[:3]:
        print(f"- {insight}")

    # Print some recommendations
    for rec in analysis.get("recommendations", [])[:3]:
        print(f"- {rec}")