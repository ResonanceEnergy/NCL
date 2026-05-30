"""Wave 14AP (2026-05-30) — Spoken brief playback via Piper TTS.

Renders the 5-lane brief (or any plain-text body) to a .wav file so
NATRIX can listen during coffee instead of reading.

Piper TTS is local, fast (~10x realtime on Apple M1), and free —
ONNX-based, ~50MB voice models cached on first use.

Default voice: `en_US-amy-medium` (clean female narrator). Override
via NCL_PIPER_VOICE env var. Voice catalog at:
  https://github.com/rhasspy/piper/blob/master/VOICES.md

Output layout: data/morning-brief-pro/audio/YYYY-MM-DD-{lane}.wav
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.intelligence.spoken_brief")


_PIPER_VOICE = os.getenv("NCL_PIPER_VOICE", "en_US-amy-medium")
_PIPER_VOICE_DIR = Path(
    os.getenv(
        "NCL_PIPER_VOICE_DIR",
        str(Path.home() / "dev" / "NCL" / "data" / "piper_voices"),
    )
)
_NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
_BRIEF_AUDIO_DIR = _NCL_BASE / "data" / "morning-brief-pro" / "audio"


_loaded_voice = None
_voice_load_attempted = False


def _ensure_voice():
    """Lazy-load Piper voice. Auto-download model on first use."""
    global _loaded_voice, _voice_load_attempted
    if _loaded_voice is not None:
        return _loaded_voice
    if _voice_load_attempted:
        return None
    _voice_load_attempted = True

    try:
        from piper import PiperVoice  # type: ignore
    except ImportError as e:
        log.warning("[spoken-brief] piper-tts not installed: %s", e)
        return None

    _PIPER_VOICE_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _PIPER_VOICE_DIR / f"{_PIPER_VOICE}.onnx"
    config_path = _PIPER_VOICE_DIR / f"{_PIPER_VOICE}.onnx.json"
    if not (model_path.exists() and config_path.exists()):
        _download_voice(_PIPER_VOICE, _PIPER_VOICE_DIR)
    if not (model_path.exists() and config_path.exists()):
        log.warning("[spoken-brief] voice files missing after download")
        return None

    try:
        _loaded_voice = PiperVoice.load(str(model_path), config_path=str(config_path))
        log.info("[spoken-brief] loaded Piper voice: %s", _PIPER_VOICE)
        return _loaded_voice
    except Exception as e:
        log.warning("[spoken-brief] voice load failed: %s", e)
        return None


def _download_voice(voice_name: str, dest_dir: Path) -> None:
    """Fetch voice model + config from Hugging Face into dest_dir."""
    import httpx  # already installed

    lang_locale, name, quality = voice_name.split("-", 2)
    lang_root = lang_locale.split("_", 1)[0]
    base = (
        f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        f"{lang_root}/{lang_locale}/{name}/{quality}"
    )
    onnx_url = f"{base}/{voice_name}.onnx"
    json_url = f"{base}/{voice_name}.onnx.json"
    for url, fname in ((onnx_url, f"{voice_name}.onnx"), (json_url, f"{voice_name}.onnx.json")):
        try:
            r = httpx.get(url, follow_redirects=True, timeout=120)
            r.raise_for_status()
            (dest_dir / fname).write_bytes(r.content)
            log.info("[spoken-brief] downloaded %s (%d bytes)", fname, len(r.content))
        except Exception as e:
            log.warning("[spoken-brief] download %s failed: %s", fname, e)


# ── Public API ────────────────────────────────────────────────────────


def _sanitize_for_tts(text: str) -> str:
    """Strip markdown, decode entities, collapse whitespace for TTS."""
    if not text:
        return ""
    out = text
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
    out = re.sub(r"`([^`]+)`", r"\1", out)
    out = re.sub(r"^#{1,6}\s+", "", out, flags=re.MULTILINE)
    out = out.replace("·", ",")
    out = re.sub(r"\s+", " ", out).strip()
    return out


async def render_text_to_wav(
    text: str,
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    """Render plain text to a Piper-narrated .wav file. Returns the path."""
    if not text:
        return None
    voice = _ensure_voice()
    if voice is None:
        return None

    if out_path is None:
        _BRIEF_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _BRIEF_AUDIO_DIR / f"{date.today().isoformat()}-tts.wav"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cleaned = _sanitize_for_tts(text)

    def _render() -> Path:
        import wave

        # piper-tts 1.4.x: use synthesize_wav() which handles header
        # writing internally (set_wav_format=True).
        with wave.open(str(out_path), "wb") as wav_file:
            voice.synthesize_wav(cleaned, wav_file)
        return out_path

    return await asyncio.to_thread(_render)


async def render_brief_to_wav(brief_text: str, target_date: Optional[str] = None) -> Optional[Path]:
    """Render today's brief plain-text body to a per-day .wav file."""
    if not brief_text:
        return None
    d = target_date or date.today().isoformat()
    _BRIEF_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _BRIEF_AUDIO_DIR / f"{d}-brief.wav"
    return await render_text_to_wav(brief_text, out_path)


__all__ = ["render_text_to_wav", "render_brief_to_wav"]
