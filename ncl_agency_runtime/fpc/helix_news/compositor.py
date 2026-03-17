"""Helix News — Video Compositor.

Combines avatar video segments with lower-thirds, text overlays,
transitions, and optional intro/outro into a final broadcast video.

Requires: pip install moviepy

Usage::

    comp = Compositor()
    result = comp.compose(segment_videos, "output/episode.mp4")
"""

import logging
from pathlib import Path
from typing import Any

from .config import load_config

logger = logging.getLogger(__name__)

# Ordered segment names for episode assembly
SEGMENT_ORDER = [
    "cold_open",
    "headlines",
    "market_pulse",
    "predictions",
    "alerts",
    "closing",
]


class Compositor:
    """Composes segment videos into a full broadcast episode."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        cfg = load_config(config_path)
        out_cfg = cfg.get("output", {})
        self.width = out_cfg.get("width", 1920)
        self.height = out_cfg.get("height", 1080)
        self.fps = out_cfg.get("fps", 30)
        self.output_dir = out_cfg.get("output_dir", "reports/helix_news")

    def compose(
        self,
        segment_videos: dict[str, dict[str, Any]],
        output_path: str | None = None,
        subtitles: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Compose all segment videos into a single episode.

        Args:
            segment_videos: Dict mapping segment names to result dicts
                            containing "video" paths (from AvatarEngine).
            output_path: Path for the final composed video.
            subtitles: Optional dict mapping segment names to SRT file paths.

        Returns:
            Dict with final video path and metadata.
        """
        try:
            from moviepy import CompositeVideoClip, TextClip, VideoFileClip, concatenate_videoclips  # noqa: F401
        except ImportError:
            logger.error("moviepy not installed. Install with: pip install moviepy")
            return {"error": "moviepy not installed", "video": None}

        # Collect video clips in order
        clips = []
        for seg_name in SEGMENT_ORDER:
            seg_result = segment_videos.get(seg_name)
            if not seg_result or not seg_result.get("video"):
                continue

            video_path = seg_result["video"]
            if not Path(video_path).exists():
                logger.warning("Segment video not found: %s", video_path)
                continue

            clip = VideoFileClip(video_path)

            # Add lower-third with segment label
            label = self._segment_label(seg_name)
            clip = self._add_lower_third(clip, label)

            clips.append(clip)

        if not clips:
            return {"error": "No segment videos to compose", "video": None}

        # Concatenate all segments
        final = concatenate_videoclips(clips, method="compose")

        # Write output
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not output_path:
            from datetime import datetime
            output_path = str(
                out_dir / f"episode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            )

        final.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )

        duration = final.duration if hasattr(final, 'duration') else 0

        # Cleanup
        for c in clips:
            c.close()
        final.close()
        logger.info("Episode composed: %s (%.1fs)", output_path, duration)

        return {
            "video": output_path,
            "duration_seconds": duration,
            "segments_used": len(clips),
        }

    def _add_lower_third(self, clip: Any, label: str) -> Any:
        """Overlay a lower-third label on a video clip."""
        try:
            from moviepy import CompositeVideoClip, TextClip
        except ImportError:
            return clip

        try:
            txt = TextClip(
                text=label,
                font_size=28,
                color="white",
                bg_color=(0, 0, 0, 178),
                font="C:/Windows/Fonts/arial.ttf",
                size=(self.width // 3, 50),
            )
            txt = txt.with_duration(min(5, clip.duration))
            txt = txt.with_position(("left", "bottom")).with_start(0.5)

            return CompositeVideoClip([clip, txt])
        except Exception as e:
            logger.warning("Could not add lower-third: %s", e)
            return clip

    @staticmethod
    def _segment_label(name: str) -> str:
        """Convert segment name to a display label."""
        labels = {
            "cold_open": "  NCC DAILY BRIEF  ",
            "headlines": "  TOP HEADLINES  ",
            "market_pulse": "  MARKET PULSE  ",
            "predictions": "  PREDICTION SPOTLIGHT  ",
            "alerts": "  ALERT BOARD  ",
            "closing": "  NCC HELIX NEWS  ",
        }
        return labels.get(name, f"  {name.upper().replace('_', ' ')}  ")
