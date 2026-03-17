"""Helix News — Avatar Engine.

Drives a portrait image with audio to produce a talking-head video
using Grok Imagine (xAI), SadTalker, or a static fallback.

Engines:
    - grok_imagine: Generates scene images via xAI API + Ken Burns animation
    - sadtalker: Local lip-sync (requires GPU for practical use)
    - static: Portrait image + audio overlay (fast fallback)

Usage::

    engine = AvatarEngine()
    result = engine.render("audio/cold_open.mp3", "output/cold_open.mp4")
"""

import json as _json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, ClassVar

from .config import load_config

# Ensure ffmpeg/ffprobe are on PATH (winget installs to a long path)
_FFMPEG_DIR = Path(
    r"C:\Users\gripa\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.0.1-full_build\bin"
)
if _FFMPEG_DIR.is_dir() and str(_FFMPEG_DIR) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")

logger = logging.getLogger(__name__)


class AvatarEngine:
    """Avatar rendering engine backed by SadTalker."""

    def __init__(self, config_path: str = "config/helix_news.json"):
        cfg = load_config(config_path)
        av_cfg = cfg.get("avatar", {})
        self.engine = av_cfg.get("engine", "sadtalker")
        self.source_image = av_cfg.get("source_image", "src/helix_news/assets/helix_portrait.png")
        self.sadtalker_path = av_cfg.get("sadtalker_path", "")
        self.enhancer = av_cfg.get("enhancer", "gfpgan")
        self.preprocess = av_cfg.get("preprocess", "crop")
        self.still_mode = av_cfg.get("still_mode", False)
        self.expression_scale = av_cfg.get("expression_scale", 1.0)
        self.xai_api_key = av_cfg.get("xai_api_key") or os.environ.get("GROK_API_KEY", "")
        self.grok_model = av_cfg.get("grok_model", "grok-imagine-image")

    def render(
        self,
        audio_path: str,
        output_path: str,
        source_image: str | None = None,
        segment_name: str = "",
        segment_text: str = "",
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Render a video segment from audio.

        Args:
            audio_path: Path to the audio file (WAV or MP3).
            output_path: Desired path for the output video.
            source_image: Override portrait image (used by static/sadtalker).
            segment_name: Segment identifier (e.g. 'headlines').
            segment_text: Script text for the segment (used by grok_imagine).
            subtitle_path: Optional path to SRT subtitle file.

        Returns:
            Dict with output path and metadata.
        """
        portrait = source_image or self.source_image

        if not Path(audio_path).exists():
            logger.error("Audio file not found: %s", audio_path)
            return {"error": f"Audio file not found: {audio_path}", "video": None}

        if self.engine == "grok_imagine":
            return self._render_grok_imagine(
                audio_path, output_path, segment_name, segment_text, subtitle_path,
            )
        elif self.engine == "static":
            if not Path(portrait).exists():
                return {"error": f"Source image not found: {portrait}", "video": None}
            return self._render_static(audio_path, output_path, portrait, subtitle_path)
        elif self.engine == "sadtalker":
            if not Path(portrait).exists():
                return {"error": f"Source image not found: {portrait}", "video": None}
            result = self._render_sadtalker(audio_path, output_path, portrait)
            if result.get("video"):
                return result
            logger.warning("SadTalker failed, falling back to static render")
            return self._render_static(audio_path, output_path, portrait, subtitle_path)
        else:
            logger.error("Unknown avatar engine: %s", self.engine)
            return {"error": f"Unknown engine: {self.engine}", "video": None}

    def render_segments(
        self,
        audio_files: dict[str, dict],
        output_dir: str,
        script_segments: list | None = None,
    ) -> dict[str, Any]:
        """Render all segments to videos.

        Args:
            audio_files: Dict mapping segment names to audio result dicts
                         (from TTSEngine.synthesize_segments).
            output_dir: Directory for video output files.
            script_segments: Optional list of segment dicts from ScriptGenerator
                             (each has 'name' and 'text' keys).

        Returns:
            Dict mapping segment names to video result dicts.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        # Build lookup for segment text
        seg_text_map: dict[str, str] = {}
        if script_segments:
            for seg in script_segments:
                seg_text_map[seg.get("name", "")] = seg.get("text", "")

        for name, audio_result in audio_files.items():
            audio_path = audio_result.get("audio")
            if not audio_path:
                continue

            video_path = out_dir / f"{name}.mp4"
            subtitle_file = audio_result.get("subtitles")
            result = self.render(
                audio_path, str(video_path),
                segment_name=name,
                segment_text=seg_text_map.get(name, ""),
                subtitle_path=subtitle_file,
            )
            results[name] = result
            logger.info("Rendered avatar segment '%s' → %s", name, video_path.name)

        return results

    def _render_sadtalker(
        self,
        audio_path: str,
        output_path: str,
        portrait: str,
    ) -> dict[str, Any]:
        """Run SadTalker inference to generate talking-head video.

        SadTalker CLI:
            python inference.py \\
                --driven_audio audio.wav \\
                --source_image portrait.png \\
                --enhancer gfpgan \\
                --result_dir output/
        """
        if not self.sadtalker_path:
            logger.error(
                "SadTalker path not configured. Set avatar.sadtalker_path in "
                "config/helix_news.json to the SadTalker repo directory."
            )
            return {
                "error": "SadTalker path not configured",
                "video": None,
                "setup_hint": (
                    "1. git clone https://github.com/OpenTalker/SadTalker.git\n"
                    "2. cd SadTalker && pip install -r requirements.txt\n"
                    "3. Download checkpoints (see SadTalker README)\n"
                    "4. Set avatar.sadtalker_path in config/helix_news.json"
                ),
            }

        sadtalker_dir = Path(self.sadtalker_path)
        inference_script = sadtalker_dir / "inference.py"
        if not inference_script.exists():
            logger.error("SadTalker inference.py not found at: %s", inference_script)
            return {"error": f"inference.py not found: {inference_script}", "video": None}

        out = Path(output_path).resolve()
        result_dir = out.parent
        result_dir.mkdir(parents=True, exist_ok=True)

        # Use the SadTalker venv Python (3.10) instead of the host Python
        # which may be too new (3.14+) and crash SadTalker's PyTorch code.
        venv_python = sadtalker_dir / ".venv" / "Scripts" / "python.exe"
        python_exe = str(venv_python) if venv_python.exists() else sys.executable

        cmd = [
            python_exe,
            str(inference_script),
            "--driven_audio", str(Path(audio_path).resolve()),
            "--source_image", str(Path(portrait).resolve()),
            "--result_dir", str(result_dir),
            "--preprocess", self.preprocess,
            "--expression_scale", str(self.expression_scale),
            "--size", "256",
            "--cpu",
        ]

        if self.enhancer and self.enhancer.lower() not in ("none", ""):
            cmd.extend(["--enhancer", self.enhancer])

        if self.still_mode:
            cmd.append("--still")

        logger.info("Running SadTalker: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(sadtalker_dir),
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
            )

            if proc.returncode != 0:
                logger.error("SadTalker failed (exit %d):\n%s", proc.returncode, proc.stderr[-2000:])
                return {"error": proc.stderr[-2000:], "video": None}

            # SadTalker writes output to result_dir with auto-generated name.
            # It creates a timestamped subdirectory, so search recursively.
            mp4_files = sorted(
                result_dir.rglob("*.mp4"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )

            if mp4_files:
                generated = mp4_files[0]
                if generated.name != out.name:
                    generated.rename(out)
                return {"video": str(out), "engine": "sadtalker"}
            else:
                return {"error": "No MP4 output found", "video": None}

        except subprocess.TimeoutExpired:
            logger.error("SadTalker timed out (3600s limit)")
            return {"error": "SadTalker timed out", "video": None}

    def _render_static(
        self,
        audio_path: str,
        output_path: str,
        portrait: str,
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Render a static-portrait video: portrait image + audio overlay.

        Fast fallback when SadTalker is unavailable or too slow (no GPU).
        Uses moviepy to compose the image with the audio track.
        """
        try:
            from moviepy import AudioFileClip, CompositeVideoClip, ImageClip  # noqa: F401
        except ImportError:
            logger.error("moviepy not installed — cannot render static video")
            return {"error": "moviepy not installed", "video": None}

        try:
            audio = AudioFileClip(audio_path)
            base = ImageClip(portrait).with_duration(audio.duration).with_audio(audio)

            clip = self._overlay_subtitles(base, subtitle_path)

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)

            clip.write_videofile(
                str(out),
                fps=24,
                codec="libx264",
                audio_codec="aac",
                logger=None,
            )
            clip.close()
            audio.close()

            logger.info("Static render complete: %s (%.1fs)", out.name, audio.duration)
            return {"video": str(out), "engine": "static"}

        except Exception as e:
            logger.error("Static render failed: %s", e)
            return {"error": str(e), "video": None}

    # ------------------------------------------------------------------
    # Subtitle overlay
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_srt(srt_path: str) -> list:
        """Parse an SRT file into a list of (start_sec, end_sec, text) tuples."""
        import re

        cues = []
        text = Path(srt_path).read_text(encoding="utf-8")
        # Split on blank lines to get blocks
        blocks = re.split(r"\n\s*\n", text.strip())
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            # Line 2 is the timestamp: 00:00:01,234 --> 00:00:02,567
            ts_match = re.match(
                r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)",
                lines[1],
            )
            if not ts_match:
                continue
            g = [int(x) for x in ts_match.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            content = " ".join(lines[2:])
            cues.append((start, end, content))
        return cues

    def _overlay_subtitles(self, clip: Any, subtitle_path: str | None) -> Any:
        """Burn SRT subtitles into a video clip as text overlays.

        Groups consecutive words into phrases (~8 words) for readability.
        """
        if not subtitle_path or not Path(subtitle_path).exists():
            return clip

        try:
            from moviepy import CompositeVideoClip, TextClip
        except ImportError:
            return clip

        cues = self._parse_srt(subtitle_path)
        if not cues:
            return clip

        # Group words into readable phrases (~8 words each)
        phrases = []
        buf_words: list = []
        buf_start = 0.0
        buf_end = 0.0
        for start, end, word in cues:
            if not buf_words:
                buf_start = start
            buf_words.append(word)
            buf_end = end
            if len(buf_words) >= 8:
                phrases.append((buf_start, buf_end, " ".join(buf_words)))
                buf_words = []
        if buf_words:
            phrases.append((buf_start, buf_end, " ".join(buf_words)))

        # Create text overlays
        txt_clips = []
        for start, end, text in phrases:
            dur = max(end - start, 0.3)
            try:
                txt = TextClip(
                    text=text,
                    font_size=32,
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    font="C:/Windows/Fonts/arial.ttf",
                    method="caption",
                    size=(clip.size[0] - 100, None),
                )
                txt = txt.with_duration(dur).with_start(start)
                txt = txt.with_position(("center", 0.85), relative=True)
                txt_clips.append(txt)
            except Exception as e:
                logger.debug("Subtitle clip failed: %s", e)
                continue

        if not txt_clips:
            return clip

        return CompositeVideoClip([clip, *txt_clips])

    # ------------------------------------------------------------------
    # Grok Imagine (xAI) — scene image generation + Ken Burns animation
    # ------------------------------------------------------------------

    # Visual style prompts per segment type
    _SCENE_PROMPTS: ClassVar[dict[str, str]] = {
        "cold_open": (
            "Professional futuristic TV news studio, holographic displays showing "
            "global data feeds, sleek anchor desk, dramatic blue and purple lighting, "
            "cinematic wide shot, photorealistic, 16:9 aspect ratio"
        ),
        "headlines": (
            "Split-screen news broadcast showing multiple world event thumbnails, "
            "breaking news ticker at bottom, modern newsroom aesthetic, "
            "dramatic lighting, photorealistic, 16:9"
        ),
        "market_pulse": (
            "Wall of financial trading screens showing candlestick charts and market "
            "data, green and red indicators, Bloomberg terminal aesthetic, "
            "dramatic dark room with glowing screens, photorealistic, 16:9"
        ),
        "predictions": (
            "Futuristic holographic crystal ball surrounded by data streams and "
            "probability charts, neural network visualization, sci-fi command center, "
            "purple and blue neon glow, photorealistic, 16:9"
        ),
        "alerts": (
            "Emergency operations center with red alert lighting, multiple warning "
            "displays, urgent atmosphere, radar screens, security monitoring room, "
            "photorealistic, 16:9"
        ),
        "closing": (
            "Elegant futuristic news studio closing shot, NCC logo hologram, "
            "city skyline visible through windows, golden hour lighting, "
            "cinematic wide angle, photorealistic, 16:9"
        ),
    }

    def _build_scene_prompt(self, segment_name: str, segment_text: str) -> str:
        """Build an image generation prompt from segment context."""
        base = self._SCENE_PROMPTS.get(
            segment_name,
            "Professional futuristic news broadcast studio, photorealistic, 16:9",
        )
        # Add content context from the script (first 120 chars)
        if segment_text:
            summary = segment_text[:120].replace('"', "'")
            return f"{base}. News topic context: {summary}"
        return base

    def _call_xai_image_api(self, prompt: str, output_path: Path) -> Path | None:
        """Call xAI image generation API and save the result."""
        if not self.xai_api_key:
            logger.error("GROK_API_KEY not set — cannot use grok_imagine engine")
            return None

        body = _json.dumps({
            "model": self.grok_model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        }).encode()

        req = urllib.request.Request(
            "https://api.x.ai/v1/images/generations",
            data=body,
            headers={
                "Authorization": f"Bearer {self.xai_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "NCL-HelixNews/1.0",
            },
            method="POST",
        )

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = _json.loads(resp.read().decode())

                images = data.get("data", [])
                if not images:
                    logger.error("xAI API returned no images")
                    return None

                # Decode base64 image
                img_b64 = images[0].get("b64_json", "")
                if not img_b64:
                    # Fallback: might return URL instead
                    img_url = images[0].get("url", "")
                    if img_url:
                        with urllib.request.urlopen(img_url, timeout=60) as img_resp:
                            output_path.write_bytes(img_resp.read())
                        return output_path
                    logger.error("xAI API returned no image data")
                    return None

                import base64
                output_path.write_bytes(base64.b64decode(img_b64))
                logger.info("Generated scene image: %s", output_path.name)
                return output_path

            except urllib.error.HTTPError as e:
                body_text = e.read().decode(errors="replace")[:500]
                logger.warning(
                    "xAI API error (attempt %d/3): %d %s — %s",
                    attempt + 1, e.code, e.reason, body_text,
                )
                if e.code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                return None
            except (urllib.error.URLError, TimeoutError) as e:
                logger.warning("xAI API network error (attempt %d/3): %s", attempt + 1, e)
                time.sleep(3)
                continue

        return None

    def _render_grok_imagine(
        self,
        audio_path: str,
        output_path: str,
        segment_name: str,
        segment_text: str,
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Generate a scene image via Grok Imagine and animate with Ken Burns."""
        try:
            from moviepy import AudioFileClip, ImageClip
        except ImportError:
            return {"error": "moviepy not installed", "video": None}

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        scene_img = out.parent / f"{segment_name}_scene.png"

        # Generate scene image
        prompt = self._build_scene_prompt(segment_name, segment_text)
        logger.info("Generating scene for '%s': %s", segment_name, prompt[:80])

        result_path = self._call_xai_image_api(prompt, scene_img)
        if not result_path:
            logger.warning("Grok Imagine failed for '%s', falling back to static", segment_name)
            portrait = self.source_image
            if Path(portrait).exists():
                return self._render_static(audio_path, output_path, portrait, subtitle_path)
            return {"error": "Grok Imagine failed and no fallback portrait", "video": None}

        # Compose video: Ken Burns (slow zoom) + audio
        try:
            audio = AudioFileClip(audio_path)
            duration = audio.duration

            img_clip = ImageClip(str(result_path))
            w, h = img_clip.size

            # Ken Burns: slow zoom from 100% to 115% over the segment duration
            def ken_burns_zoom(get_frame, t):
                """Apply a slow zoom effect."""
                import numpy as np
                from PIL import Image

                frame = get_frame(t)
                progress = t / max(duration, 0.1)
                scale = 1.0 + 0.15 * progress  # 100% → 115%

                img = Image.fromarray(frame)
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)

                # Center crop back to original size
                left = (new_w - w) // 2
                top = (new_h - h) // 2
                img = img.crop((left, top, left + w, top + h))
                return np.array(img)

            clip = img_clip.with_duration(duration)
            clip = clip.transform(ken_burns_zoom)
            clip = clip.with_audio(audio)

            clip = self._overlay_subtitles(clip, subtitle_path)

            clip.write_videofile(
                str(out),
                fps=24,
                codec="libx264",
                audio_codec="aac",
                logger=None,
            )

            clip.close()
            audio.close()

            logger.info(
                "Grok Imagine render complete: %s (%.1fs)",
                out.name, duration,
            )
            return {"video": str(out), "engine": "grok_imagine", "scene_image": str(result_path)}

        except Exception as e:
            logger.error("Grok Imagine video composition failed: %s", e)
            return {"error": str(e), "video": None}
