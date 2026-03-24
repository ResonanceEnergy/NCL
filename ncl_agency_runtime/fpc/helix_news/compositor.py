"""Helix News — Video Compositor.

Combines avatar video segments into a final broadcast episode using ffmpeg
concat demuxer (no moviepy dependency — faster and more stable).

Usage::

    comp = Compositor()
    result = comp.compose(segment_videos, "output/episode.mp4")
"""

import logging
import subprocess
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
    """Composes segment videos into a full broadcast episode via ffmpeg."""

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
        ticker_filter: str = "",
    ) -> dict[str, Any]:
        """Compose all segment videos into a single episode via ffmpeg concat.

        Args:
            segment_videos: Dict mapping segment names to result dicts
                            containing "video" paths (from AvatarEngine).
            output_path: Path for the final composed video.
            subtitles: Optional dict mapping segment names to SRT file paths.

        Returns:
            Dict with final video path and metadata.
        """
        # Collect video clips in order
        clip_paths: list[str] = []
        for seg_name in SEGMENT_ORDER:
            seg_result = segment_videos.get(seg_name)
            if not seg_result or not seg_result.get("video"):
                continue

            video_path = seg_result["video"]
            if not Path(video_path).exists():
                logger.warning("Segment video not found: %s", video_path)
                continue

            clip_paths.append(video_path)

        if not clip_paths:
            return {"error": "No segment videos to compose", "video": None}

        # Write output
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        if not output_path:
            from datetime import datetime

            output_path = str(out_dir / f"episode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Build ffmpeg concat demuxer list
        concat_list = out.parent / "concat_list.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for cp in clip_paths:
                escaped = str(Path(cp).resolve()).replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        # Build video filter: upscale + optional ticker
        vf_parts = [f"scale={self.width}:{self.height}:flags=lanczos", f"fps={self.fps}"]
        if ticker_filter:
            vf_parts.append(ticker_filter)
        vf_chain = ",".join(vf_parts)

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-vf",
            vf_chain,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0 or not out.exists():
            logger.error("ffmpeg compose failed: %s", result.stderr[-500:])
            # Keep concat_list.txt for debugging on failure
            return {"error": f"ffmpeg compose failed: {result.stderr[-200:]}", "video": None}

        concat_list.unlink(missing_ok=True)

        # Probe final duration
        dur_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
            capture_output=True,
            text=True,
        )
        try:
            duration = float(dur_result.stdout.strip())
        except ValueError:
            duration = 0.0

        logger.info("Episode composed: %s (%.1fs, %d segments)", out.name, duration, len(clip_paths))

        return {
            "video": output_path,
            "duration_seconds": duration,
            "segments_used": len(clip_paths),
        }
