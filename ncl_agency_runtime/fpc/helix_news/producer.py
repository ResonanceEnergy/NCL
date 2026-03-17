"""Helix News — Producer.

Orchestrates the full pipeline: script → TTS → avatar → composition.
Can run the full pipeline or individual stages.

Usage::

    producer = Producer()

    # Full pipeline (script → audio → avatar → video)
    result = producer.produce()

    # Script only (no GPU needed)
    script = producer.run_script()

    # Script + audio (needs edge-tts)
    result = producer.run_audio()
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .avatar_engine import AvatarEngine
from .compositor import Compositor
from .config import load_config
from .script_generator import ScriptGenerator
from .tts_engine import TTSEngine

logger = logging.getLogger(__name__)


class Producer:
    """Orchestrates the Helix News production pipeline."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.output_dir = self.cfg["output"]["output_dir"]
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.episode_dir = Path(self.output_dir) / self.timestamp
        self.episode_dir.mkdir(parents=True, exist_ok=True)

    def produce(self) -> dict[str, Any]:
        """Run the full production pipeline.

        Stages:
            1. Generate script
            2. Synthesize audio (TTS)
            3. Render avatar video per segment
            4. Compose final episode video

        Returns:
            Dict with paths and metadata for all pipeline outputs.
        """
        result: dict[str, Any] = {
            "episode_id": f"HELIX_{self.timestamp}",
            "episode_dir": str(self.episode_dir),
            "stages": {},
        }

        # Stage 1: Script
        logger.info("Stage 1/4: Generating script...")
        script = self.run_script()
        result["stages"]["script"] = script

        if not script.get("segments"):
            logger.error("Script generation produced no segments. Aborting.")
            result["error"] = "No segments generated"
            return result

        # Stage 2: Audio
        logger.info("Stage 2/4: Synthesizing audio...")
        audio = self.run_audio(script)
        result["stages"]["audio"] = audio

        if not audio:
            logger.error("Audio synthesis produced no files. Aborting.")
            result["error"] = "No audio generated"
            return result

        # Stage 3: Avatar
        logger.info("Stage 3/4: Rendering avatar...")
        avatar = self.run_avatar(audio, script)
        result["stages"]["avatar"] = avatar

        if not avatar:
            logger.warning("Avatar rendering produced no files. Composing audio-only.")

        # Stage 4: Compose
        logger.info("Stage 4/4: Composing episode...")
        video_source = avatar if avatar else audio
        episode = self.run_compose(video_source)
        result["stages"]["compose"] = episode
        result["final_video"] = episode.get("video")

        # Save manifest
        manifest_path = self.episode_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(result, indent=2, default=str),
            encoding="utf-8",
        )

        logger.info("Episode complete: %s", result.get("final_video", "no video"))
        return result

    def run_script(self) -> dict[str, Any]:
        """Stage 1: Generate the broadcast script."""
        gen = ScriptGenerator(self.config_path)
        script = gen.generate()

        # Also save a copy in episode dir
        script_path = self.episode_dir / "script.json"
        script_path.write_text(
            json.dumps(script, indent=2, default=str),
            encoding="utf-8",
        )

        logger.info(
            "Script: %d segments, ~%s",
            len(script.get("segments", [])),
            script.get("est_duration_display", "?"),
        )
        return script

    def run_audio(
        self,
        script: dict | None = None,
    ) -> dict[str, Any]:
        """Stage 2: Synthesize all segments to audio."""
        if script is None:
            script = self.run_script()

        segments = script.get("segments", [])
        if not segments:
            return {}

        audio_dir = self.episode_dir / "audio"
        engine = TTSEngine(self.config_path)
        results = engine.synthesize_segments(segments, str(audio_dir))

        logger.info("Audio: %d segments synthesized", len(results))
        return results

    def run_avatar(
        self,
        audio_files: dict | None = None,
        script: dict | None = None,
    ) -> dict[str, Any]:
        """Stage 3: Render avatar videos from audio."""
        if audio_files is None:
            script = self.run_script()
            audio_files = self.run_audio(script)

        if not audio_files:
            return {}

        video_dir = self.episode_dir / "video"
        engine = AvatarEngine(self.config_path)
        script_segments = script.get("segments") if script else None
        results = engine.render_segments(audio_files, str(video_dir), script_segments)

        success_count = sum(1 for r in results.values() if r.get("video"))
        logger.info("Avatar: %d/%d segments rendered", success_count, len(results))
        return results

    def run_compose(
        self,
        segment_videos: dict | None = None,
    ) -> dict[str, Any]:
        """Stage 4: Compose final episode video."""
        if segment_videos is None:
            return {"error": "No segment videos provided", "video": None}

        comp = Compositor(self.config_path)
        output_path = str(self.episode_dir / "episode.mp4")
        result = comp.compose(segment_videos, output_path)
        return result
