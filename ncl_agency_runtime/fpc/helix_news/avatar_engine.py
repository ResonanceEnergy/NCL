"""Helix News — Avatar Engine.

Drives a portrait image with audio to produce a talking-head video
using Grok Imagine (xAI), SadTalker, or a static fallback.

Engines:
    - grok_imagine: Generates scene images via xAI API, anchored to a random helix reference image
    - sadtalker: Local lip-sync (requires GPU for practical use)
    - static: Portrait image + audio overlay (fast fallback)

Usage::

    engine = AvatarEngine()
    result = engine.render("audio/cold_open.mp3", "output/cold_open.mp4")
"""

import json as _json
import logging
import os
import random
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

    # Cached per-process: True=video accessible, False=tier-locked, None=not yet probed
    _video_tier_ok: ClassVar[bool | None] = None

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
        self.grok_video_model = av_cfg.get("grok_video_model", "grok-imagine-video")
        # Load Helix reference catalogue and pick one outfit for this episode
        self._episode_ref = self._load_episode_ref()

    @staticmethod
    def _load_episode_ref() -> dict | None:
        """Load a random Helix reference entry from helix_refs.json for this episode."""
        catalogue_path = Path(__file__).parent / "assets" / "helix_refs" / "helix_refs.json"
        if not catalogue_path.exists():
            return None
        try:
            entries = _json.loads(catalogue_path.read_text(encoding="utf-8"))
            # Only use entries that have a saved image on disk
            available = [e for e in entries if Path(e.get("path", "")).exists()]
            if not available:
                return None
            chosen = random.choice(available)
            logger.info(
                "Episode ref: ref_%02d — %s",
                chosen.get("id", 0),
                chosen.get("notes", ""),
            )
            return chosen
        except Exception as exc:
            logger.warning("Could not load helix_refs.json: %s", exc)
            return None

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
                audio_path,
                output_path,
                segment_name,
                segment_text,
                subtitle_path,
            )
        elif self.engine == "grok_video":
            return self._render_grok_video(
                audio_path,
                output_path,
                segment_name,
                segment_text,
                subtitle_path,
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
                audio_path,
                str(video_path),
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
            "--driven_audio",
            str(Path(audio_path).resolve()),
            "--source_image",
            str(Path(portrait).resolve()),
            "--result_dir",
            str(result_dir),
            "--preprocess",
            self.preprocess,
            "--expression_scale",
            str(self.expression_scale),
            "--size",
            "256",
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
    # Grok Imagine (xAI) — reference-guided scene generation
    # ------------------------------------------------------------------

    # Helix's consistent visual identity — prepended to every scene prompt
    # so she appears as the on-camera anchor in every Grok Imagine render.
    _HELIX_ANCHOR: ClassVar[str] = (
        "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
        "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
        "blazer with subtle circuit-pattern trim, seated at a futuristic illuminated "
        "glass anchor desk, making direct fourth-wall eye contact with the camera, "
        "confident composed expression"
    )

    # Visual style prompts per segment type — Helix is always in frame
    _SCENE_PROMPTS: ClassVar[dict[str, str]] = {
        "cold_open": (
            "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
            "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
            "blazer with subtle circuit-pattern trim, seated at a futuristic illuminated "
            "glass anchor desk, making direct fourth-wall eye contact with the camera, "
            "confident composed expression, "
            "futuristic broadcast studio background, holographic globe rotating behind her, "
            "global data feeds on screens, dramatic blue and purple studio lighting, "
            "photorealistic, 16:9 aspect ratio"
        ),
        "headlines": (
            "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
            "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
            "blazer with subtle circuit-pattern trim, seated at a futuristic illuminated "
            "glass anchor desk, making direct fourth-wall eye contact with the camera, "
            "breaking news set, split-screen world event thumbnails flanking her, "
            "live news ticker scrolling below, modern newsroom aesthetic, "
            "dramatic key lighting, photorealistic, 16:9"
        ),
        "market_pulse": (
            "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
            "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
            "blazer, seated at a futuristic illuminated glass anchor desk, "
            "fourth-wall eye contact, confident expression, "
            "financial trading floor background, wall of candlestick charts and market data "
            "screens behind her, green and red indicators glowing, Bloomberg terminal aesthetic, "
            "dramatic dark room with screen-glow, photorealistic, 16:9"
        ),
        "predictions": (
            "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
            "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
            "blazer, seated at a futuristic illuminated glass anchor desk, "
            "fourth-wall eye contact, "
            "holographic probability charts and data streams surrounding her, "
            "neural network visualization in background, sci-fi command center, "
            "purple and blue neon glow, photorealistic, 16:9"
        ),
        "alerts": (
            "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
            "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
            "blazer, seated at a futuristic illuminated glass anchor desk, "
            "serious urgent expression, fourth-wall eye contact, "
            "emergency alert set background, red warning indicators on screens behind her, "
            "urgent atmosphere, radar displays, photorealistic, 16:9"
        ),
        "closing": (
            "Helix, a professional AI news anchor, silver-chrome shoulder-length hair, "
            "sharp angular facial features, luminous blue eyes, wearing a sleek dark navy "
            "blazer, seated at a futuristic illuminated glass anchor desk, "
            "warm professional closing expression, fourth-wall eye contact, "
            "NCC logo hologram glowing behind her, city skyline visible through "
            "floor-to-ceiling windows, golden hour lighting, "
            "cinematic wide angle, photorealistic, 16:9"
        ),
    }

    def _build_scene_prompt(self, segment_name: str, segment_text: str) -> str:
        """Build an image generation prompt from segment context.

        If a reference catalogue entry was loaded for this episode, the outfit
        and camera angle from that ref replace the default hardcoded description.
        This gives Helix a new look every episode while keeping her identity.
        """
        base = self._SCENE_PROMPTS.get(
            segment_name,
            "Professional futuristic news broadcast studio, photorealistic, 16:9",
        )

        # Swap in episode ref outfit + angle if we have one
        if self._episode_ref:
            outfit = self._episode_ref.get("outfit", "")
            angle = self._episode_ref.get("angle", "")
            lighting_hint = self._episode_ref.get("lighting", "")
            if outfit:
                # Replace the static navy blazer description in the base prompt
                base = base.replace(
                    "sleek dark navy blazer with subtle circuit-pattern trim",
                    outfit,
                ).replace(
                    "sleek dark navy blazer",
                    outfit,
                )
            if angle:
                base = base.replace(
                    "making direct fourth-wall eye contact with the camera",
                    angle,
                ).replace(
                    "fourth-wall eye contact",
                    angle,
                )
            if lighting_hint:
                # Append lighting hint before the photorealistic tag
                base = base.replace(
                    "photorealistic, 16:9",
                    f"{lighting_hint}, photorealistic, 16:9",
                )

        # Append broadcast content context from the script
        if segment_text:
            summary = segment_text[:120].replace('"', "'")
            return f"{base}. News context: {summary}"
        return base

    def _call_xai_image_api(
        self,
        prompt: str,
        output_path: Path,
        ref_image_path: Path | None = None,
    ) -> Path | None:
        """Dispatch to /images/edits (with reference image) or /images/generations (text-only).

        Always tries the edits endpoint first when a reference image is supplied.
        Falls back to text-only generation on failure or when no reference exists.
        """
        if not self.xai_api_key:
            logger.error("GROK_API_KEY not set — cannot use grok_imagine engine")
            return None

        if ref_image_path and ref_image_path.exists():
            result = self._do_image_edit(prompt, output_path, ref_image_path)
            if result:
                return result
            logger.debug("Image edit endpoint unavailable — using text-only generation")
        return self._do_image_generate(prompt, output_path)

    def _do_image_generate(self, prompt: str, output_path: Path) -> Path | None:
        """Text-to-image via POST /v1/images/generations (JSON body)."""
        body = _json.dumps(
            {
                "model": self.grok_model,
                "prompt": prompt,
                "n": 1,
                "response_format": "b64_json",
            }
        ).encode()
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
        return self._execute_image_request(req, output_path)

    def _do_image_edit(self, prompt: str, output_path: Path, ref_image: Path) -> Path | None:
        """Image-to-image edit via POST /v1/images/generations with image_url field.

        xAI image editing uses the SAME endpoint as generation — just add
        ``image_url`` to the JSON body. There is no separate /images/edits route.
        The model uses the reference image as a visual anchor for Helix's appearance.
        """
        import base64

        img_mime = "image/png" if ref_image.suffix.lower() == ".png" else "image/jpeg"
        img_b64 = base64.b64encode(ref_image.read_bytes()).decode("ascii")
        data_uri = f"data:{img_mime};base64,{img_b64}"

        body = _json.dumps(
            {
                "model": self.grok_model,
                "prompt": prompt,
                "image_url": data_uri,
                "n": 1,
                "response_format": "b64_json",
            }
        ).encode()

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
        return self._execute_image_request(req, output_path)

    def _execute_image_request(self, req: urllib.request.Request, output_path: Path) -> Path | None:
        """Execute an xAI image request with 3-attempt retry, decode and save."""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = _json.loads(resp.read().decode())

                images = data.get("data", [])
                if not images:
                    logger.error("xAI API returned no images")
                    return None

                img_b64 = images[0].get("b64_json", "")
                if not img_b64:
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
                    attempt + 1,
                    e.code,
                    e.reason,
                    body_text,
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

    @staticmethod
    def _pick_random_ref_png() -> Path | None:
        """Return a random helix reference PNG from the assets catalogue."""
        refs_dir = Path(__file__).parent / "assets" / "helix_refs"
        candidates = sorted(refs_dir.glob("helix_ref_*.png"))
        return random.choice(candidates) if candidates else None

    def _build_edit_prompt(self, segment_name: str, segment_text: str) -> str:
        """Scene-only prompt for image-to-image mode.

        Character appearance is anchored by the reference image, so this prompt
        describes only the broadcast set and news context — not Helix's outfit.
        """
        scene_contexts: dict[str, str] = {
            "cold_open": (
                "futuristic broadcast studio, holographic globe rotating behind her, "
                "global data feeds on screens, dramatic blue and purple studio lighting"
            ),
            "headlines": (
                "breaking news set, split-screen world event thumbnails flanking her, "
                "live news ticker scrolling below, modern newsroom aesthetic, dramatic key lighting"
            ),
            "market_pulse": (
                "financial trading floor background, wall of candlestick charts and market data "
                "screens, green and red indicators glowing, Bloomberg terminal aesthetic, "
                "dark room with screen glow"
            ),
            "predictions": (
                "holographic probability charts and data streams surrounding her, "
                "neural network visualization background, sci-fi command center, "
                "purple and blue neon glow"
            ),
            "alerts": ("emergency alert set, red warning indicators on screens, urgent atmosphere, radar displays"),
            "closing": (
                "NCC logo hologram glowing behind her, city skyline through floor-to-ceiling "
                "windows, golden hour lighting, cinematic wide angle"
            ),
        }
        scene = scene_contexts.get(segment_name, "professional futuristic news broadcast studio")
        prompt = (
            f"Helix AI news anchor seated at illuminated glass anchor desk, {scene}, "
            f"direct fourth-wall eye contact, photorealistic 16:9 broadcast"
        )
        if segment_text:
            context = segment_text[:120].replace('"', "'")
            prompt += f". Reporting: {context}"
        return prompt

    def _build_video_prompt(self, segment_name: str, segment_text: str) -> str:
        """Motion-oriented prompt for image-to-video mode.

        Describes subtle anchor movements so Grok animates Helix naturally.
        Character appearance is driven by the reference image.
        """
        motion_contexts: dict[str, str] = {
            "cold_open": (
                "Helix AI news anchor turns to face camera with a confident smile, "
                "holographic globe rotating in background, she adjusts her earpiece and begins speaking"
            ),
            "headlines": (
                "Helix AI news anchor delivers breaking news with authoritative presence, "
                "subtle head nods, split-screen graphics flickering on screens behind her"
            ),
            "market_pulse": (
                "Helix AI news anchor gestures toward glowing market charts, "
                "candlestick graphs animating on screens, she turns back to camera to deliver key figures"
            ),
            "predictions": (
                "Helix AI news anchor with holographic probability charts swirling around her, "
                "she points to data streams, eyes scanning the display then back to camera"
            ),
            "alerts": (
                "Helix AI news anchor delivering urgent bulletin, slight forward lean, "
                "red alert indicators pulsing on screens behind her, intense focused expression"
            ),
            "closing": (
                "Helix AI news anchor giving a composed closing nod to camera, "
                "NCC logo glowing behind her, city skyline visible through floor-to-ceiling windows"
            ),
        }
        motion = motion_contexts.get(
            segment_name,
            "Helix AI news anchor speaking directly to camera in a futuristic broadcast studio, "
            "subtle natural head movements, professional newsroom setting",
        )
        if segment_text:
            context = segment_text[:80].replace('"', "'")
            motion += f". Topic: {context}"
        return motion

    def _probe_video_tier(self) -> bool:
        """Probe once whether grok-imagine-video is accessible on this API key.

        Fires a minimal text-only POST (no image, 1s duration) to check tier.
        Returns True if access is granted, False if 403 (tier-locked).
        Result is cached in AvatarEngine._video_tier_ok for the process lifetime.
        """
        body = _json.dumps(
            {
                "model": self.grok_video_model,
                "prompt": "probe",
                "duration": 1,
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.x.ai/v1/videos/generations",
            data=body,
            headers={
                "Authorization": f"Bearer {self.xai_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "NCL-HelixNews/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode())
                has_id = bool(data.get("request_id"))
                logger.info("grok-imagine-video probe: ACCESSIBLE (request_id=%s)", data.get("request_id"))
                return has_id
        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.info("grok-imagine-video probe: tier-locked (403) — will use grok_imagine this session")
                return False
            # Non-403 error (e.g. 422 bad prompt) still means we have access
            logger.info("grok-imagine-video probe: accessible (HTTP %d — tier OK)", e.code)
            return True
        except Exception as e:
            logger.warning("grok-imagine-video probe failed: %s — assuming inaccessible", e)
            return False

    def _render_grok_video(
        self,
        audio_path: str,
        output_path: str,
        segment_name: str,
        segment_text: str,
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Animate a helix reference image into video via Grok Video API.

        Flow:
          1. Pick a random helix_ref_*.png and encode it as a base64 data URI.
          2. POST to /v1/videos/generations with model=grok-imagine-video.
          3. Poll GET /v1/videos/{request_id} until status=done (up to 10 min).
          4. Download the raw MP4 clip (~8s).
          5. Loop raw clip to match audio duration and mux the TTS audio.
          Falls back to grok_imagine on any failure.
        """
        import base64

        if not self.xai_api_key:
            logger.error("GROK_API_KEY not set — cannot use grok_video engine")
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        # Probe tier access once per process — skip polling overhead on subsequent segments
        if AvatarEngine._video_tier_ok is None:
            AvatarEngine._video_tier_ok = self._probe_video_tier()

        if not AvatarEngine._video_tier_ok:
            logger.info("grok-imagine-video not yet available on this key — using grok_imagine")
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        ref_png = self._pick_random_ref_png()
        if not ref_png:
            logger.warning("No helix ref PNG — falling back to grok_imagine")
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        prompt = self._build_video_prompt(segment_name, segment_text)
        logger.info("Grok video prompt for '%s': %s", segment_name, prompt[:100])

        # Encode reference image as base64 data URI
        img_b64 = base64.b64encode(ref_png.read_bytes()).decode("ascii")
        data_uri = f"data:image/png;base64,{img_b64}"

        body = _json.dumps(
            {
                "model": self.grok_video_model,
                "prompt": prompt,
                "image_url": data_uri,
                "duration": 8,
                "aspect_ratio": "16:9",
                "resolution": "480p",
            }
        ).encode()

        start_req = urllib.request.Request(
            "https://api.x.ai/v1/videos/generations",
            data=body,
            headers={
                "Authorization": f"Bearer {self.xai_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "NCL-HelixNews/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(start_req, timeout=30) as resp:
                start_data = _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="replace")[:500]
            logger.error("Grok video start failed %d: %s", e.code, err_body)
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error("Grok video start network error: %s", e)
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        request_id = start_data.get("request_id")
        if not request_id:
            logger.error("Grok video: no request_id in response: %s", start_data)
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        logger.info("Grok video request started: %s — polling up to 10 min", request_id)

        # Poll for completion (120 × 5s = 10 minutes)
        video_url: str | None = None
        for poll_num in range(120):
            time.sleep(5)
            poll_req = urllib.request.Request(
                f"https://api.x.ai/v1/videos/{request_id}",
                headers={
                    "Authorization": f"Bearer {self.xai_api_key}",
                    "User-Agent": "NCL-HelixNews/1.0",
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(poll_req, timeout=30) as resp:
                    poll_data = _json.loads(resp.read().decode())
            except Exception as e:
                logger.warning("Grok video poll error (attempt %d): %s", poll_num + 1, e)
                continue

            status = poll_data.get("status", "pending")
            if status == "done":
                video_url = poll_data.get("video", {}).get("url")
                logger.info("Grok video ready after ~%ds", (poll_num + 1) * 5)
                break
            elif status in ("expired", "failed"):
                logger.error("Grok video %s: %s", status, poll_data)
                return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)
            if poll_num % 12 == 0:
                logger.info("Grok video still pending... (%ds elapsed)", (poll_num + 1) * 5)

        if not video_url:
            logger.warning("Grok video timed out — falling back to grok_imagine")
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        # Download raw animated clip
        raw_clip = out.parent / f"{segment_name}_raw_video.mp4"
        try:
            with urllib.request.urlopen(video_url, timeout=120) as resp:
                raw_clip.write_bytes(resp.read())
            logger.info("Downloaded Grok video clip: %s", raw_clip.name)
        except Exception as e:
            logger.error("Grok video download failed: %s", e)
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        # Get TTS audio duration via ffprobe
        dur_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                audio_path,
            ],
            capture_output=True,
            text=True,
        )
        try:
            audio_duration = float(dur_result.stdout.strip())
        except ValueError:
            audio_duration = 30.0

        # Loop raw clip to audio length, mux TTS audio, scale to 720p broadcast
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(raw_clip),
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            str(audio_duration),
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
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

        ffmpeg_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        raw_clip.unlink(missing_ok=True)

        if ffmpeg_result.returncode != 0:
            logger.error("ffmpeg loop/mux failed: %s", ffmpeg_result.stderr[-500:])
            return self._render_grok_imagine(audio_path, output_path, segment_name, segment_text, subtitle_path)

        logger.info("Grok video render complete: %s (%.1fs looped)", out.name, audio_duration)
        return {
            "video": str(out),
            "engine": "grok_video",
            "ref": ref_png.name,
            "request_id": request_id,
        }

    def _render_grok_imagine(
        self,
        audio_path: str,
        output_path: str,
        segment_name: str,
        segment_text: str,
        subtitle_path: str | None = None,
    ) -> dict[str, Any]:
        """Generate a scene image via Grok Imagine and compose into video.

        Picks a fresh random helix reference PNG per segment and sends it to
        /v1/images/edits so Grok uses Helix's appearance as a visual anchor.
        Falls back to text-only /v1/images/generations if no refs exist or the
        edits endpoint is unavailable. No Ken Burns zoom — pure static frame.
        """
        try:
            from moviepy import AudioFileClip, ImageClip
        except ImportError:
            return {"error": "moviepy not installed", "video": None}

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        scene_img = out.parent / f"{segment_name}_scene.png"

        # Pick a fresh random reference image for this segment
        ref_png = self._pick_random_ref_png()
        if ref_png:
            logger.info("Using helix ref: %s", ref_png.name)
            prompt = self._build_edit_prompt(segment_name, segment_text)
        else:
            prompt = self._build_scene_prompt(segment_name, segment_text)

        logger.info("Generating scene for '%s': %s", segment_name, prompt[:80])

        result_path = self._call_xai_image_api(prompt, scene_img, ref_image_path=ref_png)
        if not result_path:
            logger.warning("Grok Imagine failed for '%s', falling back to static", segment_name)
            portrait = self.source_image
            if Path(portrait).exists():
                return self._render_static(audio_path, output_path, portrait, subtitle_path)
            return {"error": "Grok Imagine failed and no fallback portrait", "video": None}

        # Compose video: static image + audio (no Ken Burns)
        try:
            audio = AudioFileClip(audio_path)
            clip = ImageClip(str(result_path)).with_duration(audio.duration).with_audio(audio)
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

            logger.info("Grok Imagine render complete: %s (%.1fs)", out.name, audio.duration)
            return {
                "video": str(out),
                "engine": "grok_imagine",
                "scene_image": str(result_path),
                "ref": ref_png.name if ref_png else None,
            }

        except Exception as e:
            logger.error("Grok Imagine video composition failed: %s", e)
            return {"error": str(e), "video": None}
