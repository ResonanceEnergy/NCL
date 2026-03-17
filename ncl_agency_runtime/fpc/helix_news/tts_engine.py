"""Helix News — TTS Engine.

Converts script text to speech audio files using edge-tts.
Generates WAV/MP3 and optional SRT subtitle files per segment.

Requires: pip install edge-tts

Usage::

    engine = TTSEngine()
    result = engine.synthesize("Hello, this is Helix.", "output/segment.mp3")
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Force aiohttp to use the threaded resolver instead of aiodns
# (aiodns fails on Python 3.14 with DNS resolution errors)
os.environ.setdefault("AIOHTTP_NO_EXTENSIONS", "1")

from .config import load_config

logger = logging.getLogger(__name__)


class TTSEngine:
    """Text-to-speech engine backed by edge-tts."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        cfg = load_config(config_path)
        tts_cfg = cfg.get("tts", {})
        self.voice = tts_cfg.get("voice", "en-US-AriaNeural")
        self.rate = tts_cfg.get("rate", "+5%")
        self.pitch = tts_cfg.get("pitch", "+0Hz")
        self.output_format = tts_cfg.get("output_format", "mp3")

    def synthesize(
        self,
        text: str,
        output_path: str,
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Synthesize text to audio file.

        Args:
            text: The script text to speak.
            output_path: Path for the audio output file.
            subtitle_path: Optional path for SRT subtitle file.

        Returns:
            Dict with output paths and metadata.
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        result = asyncio.run(self._run_edge_tts(text, out, subtitle_path))
        return result

    def synthesize_segments(
        self,
        segments: list,
        output_dir: str,
    ) -> dict[str, Any]:
        """Synthesize all script segments into separate audio files.

        Args:
            segments: List of segment dicts (from ScriptGenerator output).
            output_dir: Directory for audio output files.

        Returns:
            Dict mapping segment names to audio file paths.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        for seg in segments:
            name = seg["name"]
            text = seg["text"]
            if not text.strip():
                continue

            audio_path = out_dir / f"{name}.{self.output_format}"
            srt_path = out_dir / f"{name}.srt"

            result = self.synthesize(text, str(audio_path), str(srt_path))
            results[name] = result
            logger.info("Synthesized segment '%s' → %s", name, audio_path.name)

        return results

    async def _run_edge_tts(
        self,
        text: str,
        output_path: Path,
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Run edge-tts to generate audio and optional subtitles."""
        try:
            import edge_tts
        except ImportError:
            logger.error(
                "edge-tts not installed. Install with: pip install edge-tts"
            )
            return {"error": "edge-tts not installed", "audio": None}

        # Force aiohttp to use the threaded resolver (aiodns fails on 3.14)
        try:
            import aiohttp
            aiohttp.resolver.DefaultResolver = aiohttp.resolver.ThreadedResolver
        except Exception:
            pass

        communicate = edge_tts.Communicate(
            text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
            boundary="WordBoundary" if subtitle_path else "SentenceBoundary",
        )

        # Stream once — collect audio and subtitle data in a single pass
        sub_gen = edge_tts.SubMaker() if subtitle_path else None
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
            elif chunk["type"] == "WordBoundary" and sub_gen is not None:
                sub_gen.feed(chunk)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_data)

        result: dict[str, Any] = {
            "audio": str(output_path),
            "voice": self.voice,
            "rate": self.rate,
        }

        # Write subtitles if requested
        if subtitle_path and sub_gen is not None:
            srt_out = Path(subtitle_path)
            srt_text = sub_gen.get_srt()
            if srt_text:
                srt_out.write_text(srt_text, encoding="utf-8")
                result["subtitles"] = str(srt_out)

        return result

    @staticmethod
    def list_voices(locale: str = "en") -> None:
        """Print available voices for a locale (CLI helper)."""
        subprocess.run(
            [sys.executable, "-m", "edge_tts", "--list-voices"],
            check=False,
        )
