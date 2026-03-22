"""Helix News — Clip Cache & Incremental Renderer.

Pre-renders individual topic clips throughout the day so the evening
brief can be assembled in under 60 seconds instead of 3-10 minutes.

Architecture:
    1. **ClipCache** — Manages a manifest of pre-rendered clips keyed by
       prediction hash. Knows which clips are fresh vs stale.
    2. **IncrementalRenderer** — Compares current predictions against the
       cache, renders only the delta (new/changed predictions).
    3. **BriefAssembler** — At brief time, picks the top N cached clips by
       impact score, generates a fresh intro + outro, and composites the
       final episode in ~30-60 seconds.

Usage::

    # During the day (08:00, 12:00, 16:00) — called by daemon
    renderer = IncrementalRenderer()
    renderer.render_new_clips()

    # At 18:00 — called by daemon
    assembler = BriefAssembler()
    result = assembler.assemble()  # → episode.mp4 in < 60s

CLI::

    python -m ncl_agency_runtime.fpc.helix_news.clip_cache [render|assemble|status]
"""

import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import load_config

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("state/helix_clip_cache")
_MANIFEST_PATH = _CACHE_DIR / "manifest.json"

# Clips older than this are considered stale and will be re-rendered
_CLIP_MAX_AGE_HOURS = 24


def _prediction_hash(pred: dict) -> str:
    """Stable hash for a prediction — changes when topic or outcome changes."""
    key = f"{pred.get('topic', '')}|{pred.get('predicted_outcome', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
#  Clip Cache — Manifest Manager
# ═══════════════════════════════════════════════════════════════


class ClipCache:
    """Manages the pre-rendered clip inventory."""

    def __init__(self):
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict[str, dict]:
        """Load manifest from disk. Returns {pred_hash: clip_meta}."""
        if _MANIFEST_PATH.exists():
            try:
                data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Corrupt manifest, starting fresh: %s", exc)
        return {}

    def save(self) -> None:
        """Persist manifest to disk."""
        _MANIFEST_PATH.write_text(
            json.dumps(self.manifest, indent=2, default=str),
            encoding="utf-8",
        )

    def has_fresh_clip(self, pred_hash: str) -> bool:
        """Check if a clip exists and is still fresh."""
        entry = self.manifest.get(pred_hash)
        if not entry:
            return False
        # Check file still exists on disk
        if not Path(entry.get("video", "")).exists():
            return False
        # Check age
        rendered_at = datetime.fromisoformat(entry["rendered_at"])
        age = datetime.now() - rendered_at
        return age < timedelta(hours=_CLIP_MAX_AGE_HOURS)

    def add_clip(self, pred_hash: str, meta: dict) -> None:
        """Register a rendered clip in the manifest."""
        self.manifest[pred_hash] = {
            **meta,
            "pred_hash": pred_hash,
            "rendered_at": datetime.now().isoformat(),
        }
        self.save()

    def get_fresh_clips(self) -> list[dict]:
        """Return all clips that are still fresh, sorted by impact_score desc."""
        fresh = []
        for h, entry in self.manifest.items():
            if self.has_fresh_clip(h):
                fresh.append(entry)
        fresh.sort(key=lambda c: c.get("impact_score", 0), reverse=True)
        return fresh

    def prune_stale(self) -> int:
        """Remove stale entries from manifest. Returns count removed."""
        stale_keys = [h for h in self.manifest if not self.has_fresh_clip(h)]
        for h in stale_keys:
            del self.manifest[h]
        if stale_keys:
            self.save()
            logger.info("Pruned %d stale clips from cache", len(stale_keys))
        return len(stale_keys)

    def status(self) -> dict[str, Any]:
        """Summary of cache state."""
        fresh = self.get_fresh_clips()
        return {
            "total_entries": len(self.manifest),
            "fresh_clips": len(fresh),
            "cache_dir": str(_CACHE_DIR),
            "top_topics": [c.get("topic", "?")[:60] for c in fresh[:5]],
        }


# ═══════════════════════════════════════════════════════════════
#  Incremental Renderer — Renders only the delta
# ═══════════════════════════════════════════════════════════════


class IncrementalRenderer:
    """Checks predictions against the clip cache and renders new ones."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.cache = ClipCache()

    def render_new_clips(self, max_clips: int = 10) -> dict[str, Any]:
        """Render clips for predictions not yet in cache.

        Returns summary with counts and paths.
        """
        from ..signal_scorer import SignalScorer
        from .avatar_engine import AvatarEngine
        from .clip_producer import _clip_script
        from .tts_engine import TTSEngine

        # Prune stale clips first
        self.cache.prune_stale()

        # Get ranked predictions
        scorer = SignalScorer()
        ranked = scorer.rank_predictions()

        # Deduplicate by topic
        seen_topics: set = set()
        unique: list[dict] = []
        for pred in ranked:
            topic = pred.get("topic", "")
            if topic not in seen_topics:
                seen_topics.add(topic)
                unique.append(pred)

        # Find which ones need rendering
        to_render: list[tuple[str, dict]] = []
        for pred in unique[:max_clips]:
            h = _prediction_hash(pred)
            if not self.cache.has_fresh_clip(h):
                to_render.append((h, pred))

        if not to_render:
            logger.info("Clip cache up to date — %d fresh clips, 0 to render", len(self.cache.get_fresh_clips()))
            return {
                "rendered": 0,
                "skipped": len(unique[:max_clips]),
                "cache_status": self.cache.status(),
            }

        logger.info(
            "Rendering %d new clips (%d already cached)", len(to_render), len(unique[:max_clips]) - len(to_render)
        )

        tts = TTSEngine(self.config_path)
        avatar = AvatarEngine(self.config_path)
        date_str = datetime.now().strftime("%A, %B %d, %Y")

        rendered = 0
        errors = 0
        for i, (pred_hash, pred) in enumerate(to_render, 1):
            topic = pred.get("topic", f"topic_{i}")
            grade = pred.get("grade", "?")
            score = pred.get("impact_score", 0)
            slug = f"clip_{pred_hash}"

            logger.info("  [%d/%d] Rendering %s — %s", i, len(to_render), grade, topic[:60])

            clip_dir = _CACHE_DIR / "clips" / slug
            clip_dir.mkdir(parents=True, exist_ok=True)

            # 1. Script
            script_text = _clip_script(pred, date_str)

            # 2. TTS
            audio_path = str(clip_dir / f"{slug}.mp3")
            srt_path = str(clip_dir / f"{slug}.srt")
            audio_result = tts.synthesize(script_text, audio_path, srt_path)

            if audio_result.get("error"):
                logger.error("  TTS failed: %s", audio_result["error"])
                errors += 1
                continue

            # 3. Avatar (Grok Imagine)
            video_path = str(clip_dir / f"{slug}.mp4")
            scene_prompt = f"News broadcast graphic: {topic[:80]}, professional, futuristic"

            video_result = avatar.render(
                audio_path=audio_result["audio"],
                output_path=video_path,
                segment_name=slug,
                segment_text=scene_prompt,
                subtitle_path=audio_result.get("subtitles"),
            )

            if video_result.get("error") and not video_result.get("video"):
                logger.error("  Avatar failed: %s", video_result["error"])
                errors += 1
                continue

            # 4. Register in cache
            self.cache.add_clip(
                pred_hash,
                {
                    "topic": topic,
                    "grade": grade,
                    "impact_score": round(score, 4),
                    "domain": pred.get("domain", ""),
                    "confidence": pred.get("confidence", 0),
                    "script": script_text,
                    "audio": audio_result.get("audio"),
                    "subtitles": audio_result.get("subtitles"),
                    "video": video_result.get("video"),
                    "engine": video_result.get("engine"),
                },
            )
            rendered += 1
            logger.info("  -> cached %s", slug)

        result = {
            "rendered": rendered,
            "errors": errors,
            "skipped": len(unique[:max_clips]) - len(to_render),
            "cache_status": self.cache.status(),
        }
        logger.info("Incremental render complete: %d new, %d errors, %d cached", rendered, errors, result["skipped"])
        return result


# ═══════════════════════════════════════════════════════════════
#  Brief Assembler — Quick evening episode from cached clips
# ═══════════════════════════════════════════════════════════════


class BriefAssembler:
    """Assembles a full HELIX episode from pre-rendered cached clips.

    At brief time (e.g. 18:00), this:
    1. Reads the clip cache for the best N clips
    2. Generates a fresh intro + outro (TTS + avatar, ~30s total)
    3. Composites into a single episode.mp4

    Total time: < 60 seconds when clips are pre-cached.
    """

    def __init__(self, config_path: str = "config/helix_news.json", max_clips: int = 8):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.max_clips = max_clips
        self.cache = ClipCache()

    def assemble(self) -> dict[str, Any]:
        """Assemble the evening brief from cached clips.

        Returns dict with episode path and metadata.
        """
        from .avatar_engine import AvatarEngine
        from .compositor import Compositor
        from .tts_engine import TTSEngine

        fresh = self.cache.get_fresh_clips()
        if not fresh:
            logger.warning("No cached clips available — falling back to full pipeline")
            return self._fallback_full_pipeline()

        selected = fresh[: self.max_clips]
        logger.info("Assembling brief from %d cached clips", len(selected))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.cfg["output"]["output_dir"]) / f"daily_{ts}"
        output_dir.mkdir(parents=True, exist_ok=True)

        tts = TTSEngine(self.config_path)
        avatar = AvatarEngine(self.config_path)

        segment_videos: dict[str, dict] = {}

        # ── Fresh intro ──────────────────────────────────────────────
        greeting = "morning" if datetime.now().hour < 12 else "afternoon" if datetime.now().hour < 18 else "evening"
        domains = sorted(set(c.get("domain", "general") for c in selected))[:4]
        domain_labels = {
            "01_crypto_defi": "crypto",
            "02_financial_markets": "markets",
            "03_macroeconomics": "the economy",
            "04_geopolitics": "global affairs",
            "05_energy_resources": "energy",
            "06_technology": "technology",
            "07_weather_climate": "climate",
            "08_health_disease": "health",
            "finance": "markets",
            "tech": "technology",
            "geopolitics": "global affairs",
            "science": "science",
            "security": "cybersecurity",
            "health": "health",
        }
        teasers = [domain_labels.get(d, d.replace("_", " ")) for d in domains]
        if len(teasers) <= 1:
            teaser_str = teasers[0] if teasers else "intelligence"
        elif len(teasers) == 2:
            teaser_str = f"{teasers[0]} and {teasers[1]}"
        else:
            teaser_str = ", ".join(teasers[:-1]) + f", and {teasers[-1]}"

        date_str = datetime.now().strftime("%A, %B %d, %Y")
        intro_text = (
            f"Good {greeting}. This is Helix, your NCC intelligence anchor. "
            f"Today is {date_str}. "
            f"We're covering {teaser_str} in tonight's brief. Let's get into it."
        )

        intro_audio = tts.synthesize(
            intro_text,
            str(output_dir / "intro.mp3"),
            str(output_dir / "intro.srt"),
        )
        if intro_audio.get("audio"):
            intro_video = avatar.render(
                audio_path=intro_audio["audio"],
                output_path=str(output_dir / "intro.mp4"),
                segment_name="cold_open",
                segment_text="Helix News anchor desk open, professional broadcast",
                subtitle_path=intro_audio.get("subtitles"),
            )
            if intro_video.get("video"):
                segment_videos["cold_open"] = intro_video

        # ── Cached clips as headline segments ────────────────────────
        for i, clip in enumerate(selected):
            video_path = clip.get("video", "")
            if video_path and Path(video_path).exists():
                seg_name = f"headlines_{i}" if i > 0 else "headlines"
                segment_videos[seg_name] = {"video": video_path}

        # ── Fresh outro ──────────────────────────────────────────────
        clip_count = len(selected)
        outro_text = (
            f"That's {clip_count} intelligence updates for tonight. "
            "Stay sharp, stay informed. "
            "This has been Helix for Natrix Command and Control. Good night."
        )
        outro_audio = tts.synthesize(
            outro_text,
            str(output_dir / "outro.mp3"),
            str(output_dir / "outro.srt"),
        )
        if outro_audio.get("audio"):
            outro_video = avatar.render(
                audio_path=outro_audio["audio"],
                output_path=str(output_dir / "outro.mp4"),
                segment_name="closing",
                segment_text="Helix News anchor desk close, professional broadcast",
                subtitle_path=outro_audio.get("subtitles"),
            )
            if outro_video.get("video"):
                segment_videos["closing"] = outro_video

        # ── Composite ────────────────────────────────────────────────
        comp = Compositor(self.config_path)
        episode_path = str(output_dir / "episode.mp4")

        # Compositor expects SEGMENT_ORDER keys — build ordered dict
        ordered_videos: dict[str, dict] = {}
        if "cold_open" in segment_videos:
            ordered_videos["cold_open"] = segment_videos["cold_open"]
        # Add clip segments in ranked order
        for key in sorted(k for k in segment_videos if k.startswith("headlines")):
            ordered_videos[key] = segment_videos[key]
        if "closing" in segment_videos:
            ordered_videos["closing"] = segment_videos["closing"]

        result = comp.compose(ordered_videos, episode_path)

        # Save assembly manifest
        manifest = {
            "episode_id": f"HELIX_DAILY_{ts}",
            "assembled_at": datetime.now().isoformat(),
            "clips_used": len(selected),
            "clips_available": len(fresh),
            "mode": "cached_assembly",
            "intro": bool(segment_videos.get("cold_open")),
            "outro": bool(segment_videos.get("closing")),
            "episode": result.get("video"),
            "clip_topics": [c.get("topic", "?") for c in selected],
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str),
            encoding="utf-8",
        )

        logger.info("Brief assembled: %s (%d clips)", result.get("video", "FAILED"), len(selected))
        return {
            **manifest,
            "final_video": result.get("video"),
            "output_dir": str(output_dir),
        }

    def _fallback_full_pipeline(self) -> dict[str, Any]:
        """If no cached clips, run the full Producer pipeline."""
        from .producer import Producer

        logger.warning("No cached clips — running full pipeline (this will take 3-10 min)")
        producer = Producer(self.config_path)
        return producer.produce()


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """CLI entry point: render | assemble | status"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "render":
        renderer = IncrementalRenderer()
        result = renderer.render_new_clips()
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "assemble":
        assembler = BriefAssembler()
        result = assembler.assemble()
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "status":
        cache = ClipCache()
        status = cache.status()
        fresh = cache.get_fresh_clips()
        print(f"Clip Cache: {status['fresh_clips']} fresh / {status['total_entries']} total")
        print(f"Cache dir:  {status['cache_dir']}")
        if fresh:
            print("\nTop cached clips:")
            for i, c in enumerate(fresh[:10], 1):
                print(
                    f"  {i}. [{c.get('grade', '?')}] {c.get('topic', '?')[:60]} (score: {c.get('impact_score', 0):.4f})"
                )
        else:
            print("\nNo cached clips. Run 'render' to pre-generate.")

    else:
        print("Usage: python -m ncl_agency_runtime.fpc.helix_news.clip_cache [render|assemble|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
