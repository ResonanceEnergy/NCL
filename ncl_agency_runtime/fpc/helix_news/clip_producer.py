"""Helix News — Clip Producer.

Generates individual short news clips (15–45 seconds each) instead of
one long episode. Each clip covers a single ranked topic from the
SignalScorer, producing a set of quick daily briefing clips.

Usage::

    from ncl_agency_runtime.fpc.helix_news.clip_producer import ClipProducer

    cp = ClipProducer()
    results = cp.produce_clips(max_clips=10)
    for clip in results["clips"]:
        print(clip["topic"], clip["grade"], clip["video"])

Pipeline per clip:
    1. Score & rank predictions via SignalScorer
    2. Generate a single-topic script (intro + insight + call-to-action)
    3. TTS → audio + SRT
    4. Grok Imagine scene → Ken Burns video with burned-in subtitles
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .avatar_engine import AvatarEngine
from .config import load_config
from .tts_engine import TTSEngine

logger = logging.getLogger(__name__)

# ── Domain labels for broadcast ──────────────────────────────────────────────

_DOMAIN_LABELS = {
    "01_crypto_defi": "Crypto & DeFi",
    "02_financial_markets": "Financial Markets",
    "03_macroeconomics": "Macroeconomics",
    "04_geopolitics": "Geopolitics",
    "05_energy_resources": "Energy & Resources",
    "06_technology": "Technology",
    "07_weather_climate": "Climate & Weather",
    "08_health_disease": "Health & Disease",
    "09_food_agriculture": "Food & Agriculture",
    "10_demographics": "Demographics",
    "11_disasters": "Disasters",
    "12_space_transport": "Space & Transport",
    "13_alt_fringe": "Fringe Intelligence",
    "14_governance": "Governance & Policy",
}


def _clean_enum(text: str) -> str:
    """Strip raw Python enum prefixes from text."""
    import re
    text = re.sub(r"\b(RiskLevel|Recommendation|Confidence)\.\w+", lambda m: m.group(0).split(".")[-1].lower(), text)
    return text


def _clip_script(prediction: dict[str, Any], date_str: str) -> str:
    """Build a short broadcast script for a single prediction."""
    topic = prediction.get("topic", "Unknown")
    outcome = prediction.get("predicted_outcome", "")
    confidence = prediction.get("confidence", 0)
    grade = prediction.get("grade", "?")
    domain = prediction.get("domain", "general")
    risk = str(prediction.get("risk_level", "moderate")).split(".")[-1].lower()
    recommendation = str(prediction.get("recommendation", "")).split(".")[-1].lower()

    domain_label = _DOMAIN_LABELS.get(domain, domain.replace("_", " ").title())

    # Clean enum artifacts
    outcome = _clean_enum(outcome)

    # Build concise clip script
    lines = [
        f"This is Helix with a {domain_label} update for {date_str}.",
        f"{topic}.",
    ]

    if outcome:
        # Truncate to ~2 sentences max
        sentences = outcome.split(". ")
        brief_outcome = ". ".join(sentences[:2])
        if not brief_outcome.endswith("."):
            brief_outcome += "."
        lines.append(brief_outcome)

    lines.append(
        f"Signal grade: {grade}. Confidence: {confidence:.0%}. Risk level: {risk}."
    )

    if recommendation and recommendation not in ("", "none", "unknown"):
        lines.append(f"Recommended action: {recommendation}.")

    lines.append("Stay sharp. This is Helix.")

    return " ".join(lines)


class ClipProducer:
    """Produces individual topic clips from ranked predictions."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.output_dir = self.cfg["output"]["output_dir"]
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.clips_dir = Path(self.output_dir) / "clips" / self.timestamp
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def produce_clips(self, max_clips: int = 10) -> dict[str, Any]:
        """Generate up to max_clips individual topic clips.

        Returns:
            Dict with metadata and list of clip results.
        """
        from ..signal_scorer import SignalScorer

        scorer = SignalScorer()
        ranked = scorer.rank_predictions()

        # Deduplicate by topic (multiple council members may have same topic)
        seen_topics: set = set()
        unique: list[dict] = []
        for pred in ranked:
            topic = pred.get("topic", "")
            if topic not in seen_topics:
                seen_topics.add(topic)
                unique.append(pred)

        top = unique[:max_clips]
        date_str = datetime.now().strftime("%A, %B %d, %Y")

        logger.info("Producing %d clips from %d unique topics", len(top), len(unique))

        tts = TTSEngine(self.config_path)
        avatar = AvatarEngine(self.config_path)

        clips: list[dict[str, Any]] = []
        for i, pred in enumerate(top, 1):
            topic = pred.get("topic", f"topic_{i}")
            grade = pred.get("grade", "?")
            score = pred.get("impact_score", 0)
            slug = f"clip_{i:02d}_{grade}"

            logger.info("Clip %d/%d [%s] %s", i, len(top), grade, topic[:60])

            # 1. Generate script
            script_text = _clip_script(pred, date_str)

            # 2. TTS → audio + SRT
            clip_dir = self.clips_dir / slug
            clip_dir.mkdir(parents=True, exist_ok=True)

            audio_path = str(clip_dir / f"{slug}.mp3")
            srt_path = str(clip_dir / f"{slug}.srt")
            audio_result = tts.synthesize(script_text, audio_path, srt_path)

            if audio_result.get("error"):
                logger.error("TTS failed for clip %d: %s", i, audio_result["error"])
                clips.append({
                    "index": i, "topic": topic, "grade": grade,
                    "score": score, "error": audio_result["error"],
                })
                continue

            # 3. Avatar → video with subtitles
            video_path = str(clip_dir / f"{slug}.mp4")
            scene_prompt = f"News broadcast graphic: {topic[:80]}, professional, futuristic"

            video_result = avatar.render(
                audio_path=audio_result["audio"],
                output_path=video_path,
                segment_name=slug,
                segment_text=scene_prompt,
                subtitle_path=audio_result.get("subtitles"),
            )

            clip_meta = {
                "index": i,
                "topic": topic,
                "grade": grade,
                "score": round(score, 4),
                "domain": pred.get("domain", ""),
                "confidence": pred.get("confidence", 0),
                "script": script_text,
                "audio": audio_result.get("audio"),
                "subtitles": audio_result.get("subtitles"),
                "video": video_result.get("video"),
                "scene_image": video_result.get("scene_image"),
                "engine": video_result.get("engine"),
                "error": video_result.get("error"),
            }
            clips.append(clip_meta)

            logger.info(
                "  → %s (%s)",
                "OK" if clip_meta["video"] else "FAILED",
                clip_meta.get("engine", "?"),
            )

        result = {
            "batch_id": f"HELIX_CLIPS_{self.timestamp}",
            "clips_dir": str(self.clips_dir),
            "total_topics": len(unique),
            "clips_produced": len([c for c in clips if c.get("video")]),
            "clips_failed": len([c for c in clips if c.get("error")]),
            "clips": clips,
        }

        # Save manifest
        manifest = self.clips_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

        logger.info(
            "Clips complete: %d/%d produced, dir=%s",
            result["clips_produced"], len(clips), self.clips_dir,
        )
        return result
