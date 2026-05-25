"""
LDE URL Ingestor — Accepts any URL, transcribes/extracts text content.

Handles:
    - YouTube videos → yt-dlp audio download → Whisper transcription
    - Other video URLs → same pipeline
    - Web articles / earnings calls → text extraction via trafilatura or readability
    - Direct text → pass-through

Reuses the proven YouTube Council transcription pipeline but adds
web article extraction and generic URL handling.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.lde.ingestor")

# Cache directory for downloaded audio
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
AUDIO_CACHE = NCL_BASE / ".cache" / "lde-audio"

# Whisper config (reuses council settings)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")


def detect_url_type(url: str) -> str:
    """Detect the type of URL for routing to the correct extractor."""
    url_lower = url.lower()

    if any(
        domain in url_lower
        for domain in [
            "youtube.com",
            "youtu.be",
            "youtube-nocookie.com",
        ]
    ):
        return "youtube"

    if any(
        domain in url_lower
        for domain in [
            "vimeo.com",
            "dailymotion.com",
            "twitch.tv",
            "rumble.com",
            "bitchute.com",
            "odysee.com",
        ]
    ):
        return "video"

    if any(ext in url_lower for ext in [".mp3", ".mp4", ".wav", ".m4a", ".webm"]):
        return "audio"

    # Default: treat as web article
    return "article"


async def ingest_url(
    url: str,
    source_type: str | None = None,
) -> dict[str, str]:
    """
    Ingest a URL and return extracted text content.

    Returns:
        {
            "url": original URL,
            "source_type": detected or provided type,
            "title": extracted title,
            "text": full extracted text / transcript,
            "duration_seconds": audio duration (0 for articles),
            "method": extraction method used,
        }
    """
    stype = source_type or detect_url_type(url)

    if stype in ("youtube", "video", "audio"):
        return await _ingest_video(url, stype)
    else:
        return await _ingest_article(url)


async def _ingest_video(url: str, source_type: str) -> dict[str, str]:
    """Download audio and transcribe a video URL."""
    log.info(f"Ingesting video: {url} (type: {source_type})")

    # Step 1: Download audio via yt-dlp
    audio_path, title = _download_audio(url)
    if not audio_path:
        log.error(f"Audio download failed for {url}")
        return {
            "url": url,
            "source_type": source_type,
            "title": "",
            "text": "",
            "duration_seconds": "0",
            "method": "failed",
        }

    # Step 2: Transcribe
    transcript, duration = await _transcribe_audio(audio_path)

    log.info(f"Transcribed: {len(transcript)} chars, {duration:.0f}s from '{title}'")

    return {
        "url": url,
        "source_type": source_type,
        "title": title,
        "text": transcript,
        "duration_seconds": str(int(duration)),
        "method": "whisper",
    }


async def _ingest_article(url: str) -> dict[str, str]:
    """Extract text from a web article URL."""
    log.info(f"Ingesting article: {url}")

    text, title = "", ""

    # Try trafilatura first (best quality for articles)
    try:
        text, title = _extract_trafilatura(url)
        if text and len(text) > 100:
            log.info(f"Extracted via trafilatura: {len(text)} chars")
            return {
                "url": url,
                "source_type": "article",
                "title": title,
                "text": text,
                "duration_seconds": "0",
                "method": "trafilatura",
            }
    except Exception as e:
        log.debug(f"trafilatura failed: {e}")

    # Fallback: newspaper3k
    try:
        text, title = _extract_newspaper(url)
        if text and len(text) > 100:
            log.info(f"Extracted via newspaper3k: {len(text)} chars")
            return {
                "url": url,
                "source_type": "article",
                "title": title,
                "text": text,
                "duration_seconds": "0",
                "method": "newspaper3k",
            }
    except Exception as e:
        log.debug(f"newspaper3k failed: {e}")

    # Fallback: httpx + basic HTML strip
    try:
        text, title = await _extract_httpx(url)
        if text and len(text) > 50:
            log.info(f"Extracted via httpx: {len(text)} chars")
            return {
                "url": url,
                "source_type": "article",
                "title": title,
                "text": text,
                "duration_seconds": "0",
                "method": "httpx",
            }
    except Exception as e:
        log.debug(f"httpx extraction failed: {e}")

    log.warning(f"All extraction methods failed for {url}")
    return {
        "url": url,
        "source_type": "article",
        "title": "",
        "text": "",
        "duration_seconds": "0",
        "method": "failed",
    }


# ── yt-dlp Audio Download ────────────────────────────────────────────────


def _download_audio(url: str) -> tuple[Optional[Path], str]:
    """Download audio from a video URL using yt-dlp. Returns (audio_path, title)."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        log.error("yt-dlp not installed. Run: pip install yt-dlp")
        return None, ""

    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(AUDIO_CACHE / "%(id)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id", "unknown")
            title = info.get("title", "Untitled")

            mp3_path = AUDIO_CACHE / f"{video_id}.mp3"
            if mp3_path.exists():
                return mp3_path, title

            # Try other extensions
            for ext in ["mp3", "m4a", "opus", "webm", "ogg"]:
                alt = AUDIO_CACHE / f"{video_id}.{ext}"
                if alt.exists():
                    return alt, title

    except Exception as e:
        log.error(f"yt-dlp download failed: {e}")

    return None, ""


# ── Whisper Transcription ─────────────────────────────────────────────────


async def _transcribe_audio(audio_path: Path) -> tuple[str, float]:
    """Transcribe audio file. Returns (timestamped_text, duration_seconds).

    W13 P1-A (2026-05-24): gated on the ``whisper`` budget key + the
    faster-whisper backend now goes through the process-wide singleton
    (``runtime.lde.whisper_singleton``) instead of constructing a fresh
    ``WhisperModel`` per call. Same anti-pattern that caused the W12
    ChromaDB Rust HNSW deadlock.
    """
    # Budget gate — even though local whisper has $0/day cap (= free),
    # routing through can_spend() lets ops disable the path via env
    # (``NCL_BUDGET_WHISPER=-1``) and lets us swap in a paid backend
    # later without touching every call site.
    try:
        from ..cost_tracker import check_budget

        if not await check_budget("whisper", 0.0):
            log.warning(
                "[INGESTOR] whisper budget exhausted — skipping transcription for %s",
                audio_path.name,
            )
            return "", 0.0
    except Exception as e:
        log.debug(f"[INGESTOR] cost gate import failed: {e}")

    # Try faster-whisper
    transcript, dur = await _try_faster_whisper(audio_path)
    if transcript:
        return transcript, dur

    # Try mlx-whisper (Apple Silicon)
    transcript, dur = _try_mlx_whisper(audio_path)
    if transcript:
        return transcript, dur

    # Try OpenAI Whisper API (gated on the "openai" budget key — Whisper
    # cloud is metered, faster-whisper local is free)
    try:
        from ..cost_tracker import check_budget

        if not await check_budget("openai", 0.006):
            log.warning(
                "[INGESTOR] openai budget exhausted — skipping cloud Whisper fallback for %s",
                audio_path.name,
            )
            return "", 0.0
    except Exception:
        pass

    transcript, dur = _try_openai_whisper(audio_path)
    if transcript:
        return transcript, dur

    log.error(f"All transcription methods failed for {audio_path.name}")
    return "", 0.0


async def _try_faster_whisper(audio_path: Path) -> tuple[str, float]:
    """Transcribe via faster-whisper.

    W13 P1-A: now uses the process-wide WhisperModel singleton to avoid
    spawning a fresh CTranslate2 backend per video — the W12 deadlock
    class.
    """
    try:
        from .whisper_singleton import get_whisper_model
    except ImportError:
        return "", 0.0

    try:
        model = await get_whisper_model(
            model_size=WHISPER_MODEL,
            compute_type=WHISPER_COMPUTE_TYPE,
            device=WHISPER_DEVICE,
        )
    except ImportError:
        # faster_whisper not installed
        return "", 0.0
    except Exception as e:
        log.warning(f"faster-whisper singleton init failed: {e}")
        return "", 0.0

    try:
        start = time.monotonic()
        # .transcribe() is sync — push to a worker thread so the event
        # loop stays responsive while CTranslate2 chews on the audio.
        def _run_transcribe():
            return model.transcribe(
                str(audio_path),
                beam_size=5,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
            )


        import asyncio as _asyncio
        segments_iter, info = await _asyncio.to_thread(_run_transcribe)

        lines = []
        last_end = 0.0
        for seg in segments_iter:
            m, s = divmod(int(seg.start), 60)
            h, m = divmod(m, 60)
            ts = f"[{h}:{m:02d}:{s:02d}]" if h > 0 else f"[{m:02d}:{s:02d}]"
            lines.append(f"{ts} {seg.text.strip()}")
            last_end = seg.end

        elapsed = time.monotonic() - start
        log.info(f"faster-whisper: {len(lines)} segments, {last_end:.0f}s audio in {elapsed:.1f}s")
        return "\n".join(lines), last_end
    except Exception as e:
        log.warning(f"faster-whisper failed: {e}")
        return "", 0.0


def _try_mlx_whisper(audio_path: Path) -> tuple[str, float]:
    """Transcribe via mlx-whisper (Apple Silicon native)."""
    try:
        import mlx_whisper
    except ImportError:
        return "", 0.0

    try:
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=f"mlx-community/whisper-{WHISPER_MODEL}-mlx",
            language="en",
        )
        lines = []
        last_end = 0.0
        for seg in result.get("segments", []):
            m, s = divmod(int(seg["start"]), 60)
            lines.append(f"[{m:02d}:{s:02d}] {seg['text'].strip()}")
            last_end = seg["end"]
        return "\n".join(lines), last_end
    except Exception as e:
        log.warning(f"mlx-whisper failed: {e}")
        return "", 0.0


def _try_openai_whisper(audio_path: Path) -> tuple[str, float]:
    """Transcribe via OpenAI Whisper API (cloud fallback)."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return "", 0.0

    file_size = audio_path.stat().st_size
    if file_size > 25 * 1024 * 1024:
        log.warning(f"Audio too large for OpenAI API ({file_size / 1e6:.1f}MB)")
        return "", 0.0

    try:
        import httpx

        with open(audio_path, "rb") as f:
            response = httpx.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, f, "audio/mpeg")},
                data={
                    "model": "whisper-1",
                    "language": "en",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                },
                timeout=300.0,
            )
            response.raise_for_status()
            data = response.json()

        lines = []
        last_end = 0.0
        for seg in data.get("segments", []):
            m, s = divmod(int(seg["start"]), 60)
            lines.append(f"[{m:02d}:{s:02d}] {seg['text'].strip()}")
            last_end = seg["end"]
        return "\n".join(lines), last_end
    except Exception as e:
        log.warning(f"OpenAI Whisper API failed: {e}")
        return "", 0.0


# ── Web Article Extraction ────────────────────────────────────────────────


def _extract_trafilatura(url: str) -> tuple[str, str]:
    """Extract article text via trafilatura."""
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return "", ""
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    # Try to get title
    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata and metadata.title else ""
    return text or "", title


def _extract_newspaper(url: str) -> tuple[str, str]:
    """Extract article text via newspaper3k."""
    from newspaper import Article

    article = Article(url)
    article.download()
    article.parse()
    return article.text or "", article.title or ""


_ingestor_client: Optional["httpx.AsyncClient"] = None  # noqa: F821
_ingestor_lock: Optional["asyncio.Lock"] = None  # noqa: F821


def _get_ingestor_lock() -> "asyncio.Lock":  # noqa: F821
    global _ingestor_lock
    import asyncio

    if _ingestor_lock is None:
        _ingestor_lock = asyncio.Lock()
    return _ingestor_lock


async def _get_ingestor_client() -> "httpx.AsyncClient":  # noqa: F821
    """Return a shared HTTP client for LDE ingestor fetches."""
    global _ingestor_client

    import httpx

    if _ingestor_client is None or _ingestor_client.is_closed:
        async with _get_ingestor_lock():
            if _ingestor_client is None or _ingestor_client.is_closed:
                _ingestor_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    return _ingestor_client


async def _extract_httpx(url: str) -> tuple[str, str]:
    """Basic HTTP fetch + HTML tag stripping as last resort."""
    client = await _get_ingestor_client()
    resp = await client.get(
        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) NCL-LDE/1.0"}
    )
    resp.raise_for_status()
    html = resp.text

    # Extract title
    title = ""
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()

    # Strip HTML tags (crude but functional as last resort)
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Take only the meaty middle (skip nav/footer noise)
    if len(text) > 2000:
        text = text[500:-500]
    return text, title
