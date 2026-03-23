"""Helix News — Script Generator.

Aggregates data from FPC predictions, alert engine, signal scorer, and
event logs to produce a structured news anchor script for Helix.

Each script has segments (cold_open, headlines, market_pulse, predictions,
alerts, closing) with text, estimated duration, and metadata.

Usage::

    gen = ScriptGenerator()
    script = gen.generate()
    print(script["full_text"])
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import load_config

logger = logging.getLogger(__name__)

# Approximate words per minute for a news anchor pace
WPM_NEWS_ANCHOR = 150

# Domain keywords for classifying predictions into segments
_FINANCE_KEYWORDS = frozenset(
    [
        "bitcoin",
        "crypto",
        "market",
        "stock",
        "s&p",
        "nasdaq",
        "financial",
        "treasury",
        "bond",
        "yield",
        "gold",
        "oil",
        "etf",
        "fed",
        "inflation",
        "interest rate",
        "currency",
        "forex",
        "trading",
        "equity",
        "recession",
    ]
)
_TECH_KEYWORDS = frozenset(
    [
        "ai",
        "llm",
        "gpt",
        "machine learning",
        "neural",
        "deep learning",
        "technology",
        "software",
        "automation",
        "robot",
        "quantum",
        "computing",
        "agent",
        "copilot",
        "model",
        "openai",
        "anthropic",
        "google",
    ]
)
_GEO_KEYWORDS = frozenset(
    [
        "geopolitics",
        "china",
        "russia",
        "nato",
        "sanctions",
        "diplomacy",
        "conflict",
        "election",
        "tariff",
        "trade war",
        "military",
        "treaty",
    ]
)
_SCIENCE_KEYWORDS = frozenset(
    [
        "research",
        "breakthrough",
        "physics",
        "biology",
        "chemistry",
        "climate",
        "energy",
        "fusion",
        "space",
        "nasa",
        "crispr",
    ]
)
_SECURITY_KEYWORDS = frozenset(
    [
        "cyber",
        "breach",
        "hack",
        "vulnerability",
        "ransomware",
        "threat",
        "malware",
        "exploit",
        "zero-day",
        "privacy",
        "surveillance",
    ]
)
_HEALTH_KEYWORDS = frozenset(
    [
        "health",
        "longevity",
        "medical",
        "disease",
        "vaccine",
        "drug",
        "fitness",
        "nutrition",
        "sleep",
        "aging",
        "cancer",
    ]
)


def _classify_domain(topic: str) -> str:
    """Classify a prediction topic into a domain category."""
    low = topic.lower()
    for kw in _FINANCE_KEYWORDS:
        if kw in low:
            return "finance"
    for kw in _TECH_KEYWORDS:
        if kw in low:
            return "tech"
    for kw in _GEO_KEYWORDS:
        if kw in low:
            return "geopolitics"
    for kw in _SCIENCE_KEYWORDS:
        if kw in low:
            return "science"
    for kw in _SECURITY_KEYWORDS:
        if kw in low:
            return "security"
    for kw in _HEALTH_KEYWORDS:
        if kw in low:
            return "health"
    return "general"


def _readable_risk(raw: str) -> str:
    """Convert RiskLevel.LOW → 'low', etc."""
    s = str(raw)
    if "." in s:
        s = s.split(".")[-1]
    return s.lower()


class Segment:
    """A single segment of the broadcast."""

    def __init__(self, name: str, text: str, metadata: dict | None = None):
        self.name = name
        self.text = text
        self.metadata = metadata or {}
        self.word_count = len(text.split())
        self.est_seconds = int((self.word_count / WPM_NEWS_ANCHOR) * 60)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "text": self.text,
            "word_count": self.word_count,
            "est_seconds": self.est_seconds,
            "metadata": self.metadata,
        }


class ScriptGenerator:
    """Generates a news anchor script from FPC/NCC data sources."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        self.cfg = load_config(config_path)
        self.max_minutes = self.cfg.get("episode_max_minutes", 10)
        self.seg_cfg = self.cfg.get("segments", {})
        self.now = datetime.now()
        self.date_str = self.now.strftime("%A, %B %d, %Y")
        self.time_str = self.now.strftime("%H:%M")
        self._headline_topics: set[str] = set()

    def generate(self) -> dict[str, Any]:
        """Generate the full broadcast script.

        Returns a dict with:
            - segments: list of segment dicts
            - full_text: concatenated script
            - metadata: episode info
        """
        # Load and deduplicate predictions ONCE
        all_preds = self._load_deduplicated_predictions()

        segments = []
        segments.append(self._cold_open(all_preds))
        segments.append(self._headlines(all_preds))
        segments.append(self._market_pulse(all_preds))
        segments.append(self._predictions(all_preds))
        segments.append(self._alerts())
        segments.append(self._closing())

        # Filter out empty segments
        segments = [s for s in segments if s.text.strip()]

        full_text = "\n\n".join(s.text for s in segments)
        total_words = sum(s.word_count for s in segments)
        total_seconds = sum(s.est_seconds for s in segments)

        result = {
            "episode_id": self.now.strftime("HELIX_%Y%m%d_%H%M%S"),
            "date": self.date_str,
            "generated_at": self.now.isoformat(),
            "segments": [s.to_dict() for s in segments],
            "full_text": full_text,
            "total_words": total_words,
            "est_duration_seconds": total_seconds,
            "est_duration_display": f"{total_seconds // 60}:{total_seconds % 60:02d}",
        }

        # Save script to output dir
        out_dir = Path(self.cfg["output"]["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        script_path = out_dir / f"script_{self.now.strftime('%Y%m%d_%H%M%S')}.json"
        script_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

        txt_path = out_dir / f"script_{self.now.strftime('%Y%m%d_%H%M%S')}.txt"
        txt_path.write_text(full_text, encoding="utf-8")

        logger.info("Script generated: %s (~%s)", script_path.name, result["est_duration_display"])
        return result

    # ── Segment Builders ─────────────────────────────────────────────────────

    def _cold_open(self, all_preds: list[dict]) -> Segment:
        """Opening greeting with a teaser of what's coming."""
        greeting = "morning" if self.now.hour < 12 else "afternoon" if self.now.hour < 18 else "evening"

        # Build teaser from domain diversity
        domains = set()
        for p in all_preds[:10]:
            domains.add(p.get("_domain", "general"))
        domain_labels = {
            "finance": "markets",
            "tech": "technology",
            "geopolitics": "global affairs",
            "science": "science",
            "security": "cybersecurity",
            "health": "health",
            "general": "intelligence",
        }
        teasers = [domain_labels.get(d, d) for d in sorted(domains)][:4]
        if len(teasers) == 0:
            teaser_str = "intelligence"
        elif len(teasers) == 1:
            teaser_str = teasers[0]
        elif len(teasers) == 2:
            teaser_str = f"{teasers[0]} and {teasers[1]}"
        else:
            teaser_str = ", ".join(teasers[:-1]) + f", and {teasers[-1]}"

        text = (
            f"Good {greeting}. This is Helix, your NCC intelligence anchor. "
            f"Today is {self.date_str}. "
            f"We're covering {teaser_str} in today's brief. Let's get into it."
        )
        return Segment("cold_open", text)

    def _headlines(self, all_preds: list[dict]) -> Segment:
        """Top events across ALL domains — diverse, not finance-only."""
        max_headlines = self.seg_cfg.get("headlines_count", 5)

        if not all_preds:
            text = (
                "In the headlines: No major events were flagged in the last 24 hours. "
                "All monitored domains are reporting stable conditions."
            )
            return Segment("headlines", text, {"count": 0})

        # Pick headlines with maximum domain diversity
        top = self._pick_diverse(all_preds, max_headlines)

        lines = ["Here are today's top stories."]
        used_topics = set()
        for i, item in enumerate(top, 1):
            topic = item.get("topic", "Unknown topic")
            outcome = item.get("predicted_outcome", "No details available")
            conf = item.get("confidence", 0)
            domain = item.get("_domain", "general")

            # Clean up the outcome — strip topic echoes, keep tight for broadcast
            outcome = self._clean_for_broadcast(outcome, topic)
            # If cleaning stripped everything, provide a generic directional statement
            if not outcome or len(outcome) < 10:
                outcome = "Our analysts see significant developments ahead."

            domain_tag = {
                "finance": "In markets",
                "tech": "In tech",
                "geopolitics": "On the global stage",
                "science": "In science",
                "security": "In cybersecurity",
                "health": "In health",
            }.get(domain, "Also noteworthy")

            display_topic = self._topic_for_broadcast(topic)
            line = f"Number {i}: {domain_tag} — {display_topic}. {outcome}"
            if conf > 0:
                line += f" Confidence: {conf:.0%}."
            lines.append(line)
            used_topics.add(topic)

        # Store used topics so predictions segment can avoid repeating them
        self._headline_topics = used_topics

        text = " ".join(lines)
        return Segment("headlines", text, {"count": len(top)})

    def _market_pulse(self, all_preds: list[dict]) -> Segment:
        """Financial and market conditions — only finance-domain predictions."""
        finance_preds = [p for p in all_preds if p.get("_domain") == "finance"]

        if not finance_preds:
            text = (
                "In markets: No market-specific predictions are active at this time. "
                "We'll bring you updates as the council reconvenes."
            )
            return Segment("market_pulse", text, {"count": 0})

        lines = ["Let's check the pulse on markets."]
        for item in finance_preds[:3]:
            topic = item.get("topic", "")
            outcome = self._clean_for_broadcast(item.get("predicted_outcome", ""), topic)
            if not outcome or len(outcome) < 10:
                outcome = "The council sees notable movement potential."
            risk = _readable_risk(item.get("risk_level", "medium"))
            conf = item.get("confidence", 0)
            display_topic = self._topic_for_broadcast(topic)
            lines.append(f"{display_topic}. {outcome} Risk level: {risk}. Confidence: {conf:.0%}.")

        text = " ".join(lines)
        return Segment("market_pulse", text, {"count": len(finance_preds[:3])})

    def _predictions(self, all_preds: list[dict]) -> Segment:
        """Top FPC council predictions — NON-FINANCE to avoid repeating market_pulse."""
        max_preds = self.seg_cfg.get("predictions_count", 5)

        # Exclude finance predictions (already covered in market_pulse)
        # AND exclude topics already used in headlines
        headline_topics = getattr(self, "_headline_topics", set())
        non_finance = [p for p in all_preds if p.get("_domain") != "finance" and p.get("topic") not in headline_topics]

        # If not enough non-finance, include some finance that weren't in market_pulse
        if len(non_finance) < max_preds:
            finance_extras = [
                p for p in all_preds if p.get("_domain") == "finance" and p.get("topic") not in headline_topics
            ][3:]
            non_finance.extend(finance_extras)

        if not non_finance:
            text = (
                "The prediction council has no additional forecasts to spotlight today. "
                "New predictions will appear after the next council session."
            )
            return Segment("predictions", text, {"count": 0})

        top = non_finance[:max_preds]
        lines = ["Now for the council's intelligence forecasts."]
        for i, item in enumerate(top, 1):
            topic = item.get("topic", "Unknown")
            outcome = self._clean_for_broadcast(item.get("predicted_outcome", ""), topic)
            conf = item.get("confidence", 0)
            domain = item.get("_domain", "general")

            domain_label = {
                "tech": "Technology",
                "geopolitics": "Geopolitics",
                "science": "Science",
                "security": "Cybersecurity",
                "health": "Health",
                "finance": "Markets",
            }.get(domain, "Intelligence")

            outcome = self._clean_for_broadcast(outcome, topic)
            if not outcome or len(outcome) < 10:
                outcome = "Developments are progressing in line with council expectations."

            display_topic = self._topic_for_broadcast(topic)
            line = f"Number {i}, {domain_label}: {display_topic}. {outcome} Confidence: {conf:.0%}."
            lines.append(line)

        text = " ".join(lines)
        return Segment("predictions", text, {"count": len(top)})

    def _alerts(self) -> Segment:
        """Active alerts requiring attention."""
        max_alerts = self.seg_cfg.get("max_alerts", 5)

        try:
            from ..alerting import AlertEngine

            engine = AlertEngine()
            engine.scan()
            active = engine.get_active_alerts()
        except Exception as e:
            logger.warning("Could not load alert engine: %s", e)
            active = []

        if not active:
            text = (
                "On the alert board: All clear. No active alerts at this time. "
                "All systems are operating within normal parameters."
            )
            return Segment("alerts", text, {"count": 0})

        alerts = active[:max_alerts]
        lines = [f"Attention — {len(active)} active alert{'s' if len(active) != 1 else ''}."]
        for a in alerts:
            level = a.get("level", "MEDIUM")
            title = a.get("title", "Alert")
            detail = a.get("detail", "")
            line = f"{level} alert: {title}."
            if detail:
                line += f" {detail}"
            lines.append(line)

        text = " ".join(lines)
        return Segment("alerts", text, {"count": len(active)})

    def _closing(self) -> Segment:
        """Sign-off."""
        text = f"That wraps today's brief for {self.date_str}. Stay sharp. Stay informed. This is Helix, signing off."
        return Segment("closing", text)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _topic_for_broadcast(topic: str) -> str:
        """Convert a question-form topic into a concise label for broadcast.

        'Will the Federal Reserve cut interest rates below 3%?' → 'The Federal Reserve and interest rates'
        'How will AI reshape trading?' → 'AI and trading'
        """
        import re

        t = topic.rstrip("?. ")
        # Strip question prefix
        t = re.sub(r"^(?:Will|How will|How might|How could|Can|Could|Should|Is|Are|Do|Does)\s+", "", t, flags=re.I)
        # Strip trailing time references
        t = re.sub(r"\s+by\s+(?:year-end\s+)?\d{4}$", "", t, flags=re.I)
        t = re.sub(r"\s+within\s+\d+\s+(?:months?|years?)(?:\s+of\s+\w+)?$", "", t, flags=re.I)
        # Break at verbs to extract the subject
        words = t.split()
        _BREAK_VERBS = frozenset(
            [
                "replace",
                "outperform",
                "reshape",
                "transform",
                "dominate",
                "disrupt",
                "change",
                "affect",
                "influence",
                "threaten",
                "achieve",
                "become",
                "give",
                "manage",
                "eliminate",
                "converge",
                "compete",
                "improve",
                "cut",
                "create",
                "produce",
                "win",
                "match",
                "make",
                "drive",
                "accelerate",
            ]
        )
        if len(words) > 3:
            for i, w in enumerate(words):
                if w.lower() in _BREAK_VERBS and i >= 1:
                    t = " ".join(words[:i])
                    break
        # Capitalize first letter
        if t and t[0].islower():
            t = t[0].upper() + t[1:]
        # Cap length
        words = t.split()
        if len(words) > 8:
            t = " ".join(words[:8])
        return t

    @staticmethod
    def _clean_for_broadcast(text: str, topic: str = "") -> str:
        """Clean raw prediction text for spoken broadcast delivery."""
        if not text:
            return ""
        import re

        # Remove raw enum strings like RiskLevel.LOW, Recommendation.BUY
        text = re.sub(r"\b\w+Level\.\w+\b", lambda m: m.group().split(".")[-1].lower(), text)
        text = re.sub(r"\bRecommendation\.\w+\b", lambda m: m.group().split(".")[-1].lower(), text)
        # Strip topic-echo patterns: "Monitor {topic} closely", "suggests {topic} will"
        if topic:
            topic_escaped = re.escape(topic.rstrip("?. "))
            # Remove "Strategic recommendation: Monitor {topic} closely"
            text = re.sub(
                rf"Strategic recommendation:\s*Monitor\s+{topic_escaped}\s+closely\.?",
                "",
                text,
                flags=re.I,
            )
            # Remove "Trend analysis suggests {topic} will show steady growth"
            text = re.sub(
                rf"Trend analysis suggests\s+{topic_escaped}\s+will show steady growth\.?",
                "",
                text,
                flags=re.I,
            )
            # Remove "Risk assessment identifies moderate uncertainty in {topic}"
            text = re.sub(
                rf"Risk assessment identifies moderate uncertainty in\s+{topic_escaped}\.?",
                "",
                text,
                flags=re.I,
            )
            # Remove "Multiple scenarios developed for {topic} evolution"
            text = re.sub(
                rf"Multiple scenarios developed for\s+{topic_escaped}\s+evolution\.?",
                "",
                text,
                flags=re.I,
            )
        # Truncate very long outcomes to first 2 sentences
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) > 3:
            text = " ".join(sentences[:3])
        return text.strip()

    @staticmethod
    def _pick_diverse(items: list[dict], count: int) -> list[dict]:
        """Pick items with maximum domain diversity using round-robin."""
        by_domain: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            by_domain[item.get("_domain", "general")].append(item)

        # Round-robin across domains
        result = []
        domain_keys = list(by_domain.keys())
        idx = {d: 0 for d in domain_keys}
        while len(result) < count and domain_keys:
            exhausted = []
            for d in domain_keys:
                if idx[d] < len(by_domain[d]) and len(result) < count:
                    result.append(by_domain[d][idx[d]])
                    idx[d] += 1
                elif idx[d] >= len(by_domain[d]):
                    exhausted.append(d)
            for d in exhausted:
                domain_keys.remove(d)
            if not domain_keys:
                break
        return result

    # ── Data Loaders ─────────────────────────────────────────────────────────

    def _load_deduplicated_predictions(self) -> list[dict[str, Any]]:
        """Load predictions, deduplicate by topic, classify domains."""
        raw = self._load_recent_predictions()
        if not raw:
            return []

        # Deduplicate: merge multiple council member predictions per topic
        # Keep the one with highest confidence, average their confidence
        by_topic: dict[str, dict] = {}
        for p in raw:
            topic = p.get("topic", "")
            if topic not in by_topic:
                by_topic[topic] = dict(p)
                by_topic[topic]["_member_count"] = 1
                by_topic[topic]["_conf_sum"] = p.get("confidence", 0)
            else:
                existing = by_topic[topic]
                existing["_member_count"] += 1
                existing["_conf_sum"] += p.get("confidence", 0)
                # Keep higher-confidence version's outcome
                if p.get("confidence", 0) > existing.get("confidence", 0):
                    existing["predicted_outcome"] = p.get("predicted_outcome", "")
                    existing["confidence"] = p.get("confidence", 0)
                    existing["council_member"] = p.get("council_member", "")

        # Build deduplicated list with consensus confidence
        deduped = []
        for topic, item in by_topic.items():
            item["confidence"] = item["_conf_sum"] / item["_member_count"]
            item["_domain"] = _classify_domain(topic)
            deduped.append(item)

        # Sort by confidence descending
        deduped.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return deduped

    def _load_recent_predictions(self) -> list[dict[str, Any]]:
        """Load predictions from SQLite (preferred) or state/predictions.json."""
        # Try SQLite persistence first (same store as PredictionTracker)
        try:
            from ..persistence import PredictionStore

            store = PredictionStore()
            data = store.list_all()
            if data:
                cutoff = (self.now - timedelta(hours=24)).isoformat()
                recent = [p for p in data if p.get("recorded_at", p.get("timestamp", "")) >= cutoff]
                return recent if recent else data
        except Exception as e:
            logger.debug("SQLite predictions unavailable: %s", e)

        # Fallback to JSON file
        pred_file = Path("state/predictions.json")
        if not pred_file.exists():
            return []
        try:
            data = json.loads(pred_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("predictions", [])
            cutoff = (self.now - timedelta(hours=24)).isoformat()
            recent = [p for p in data if p.get("timestamp", p.get("created_at", "")) >= cutoff]
            return recent if recent else data
        except Exception as e:
            logger.warning("Failed to load predictions: %s", e)
            return []
