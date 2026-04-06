"""
YouTube Council — Audio Transcriber

Transcribes audio files using faster-whisper, optimized for Apple Silicon.
Falls back to OpenAI Whisper API if local model unavailable.

Mac Mini M4 Pro: Uses CPU with int8 quantization for good speed/quality balance.
For even faster inference, install mlx-whisper (Apple Silicon native).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from ..shared.models import Transcript, TranscriptSegment

log = logging.getLogger("ncl.councils.youtube.transcriber")

# Model config
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # cpu for M4 Pro (no CUDA)
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8 for speed on CPU
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))


def transcribe_audio(
    audio_path: Path,
    video_id: str = "",
    language: str = "en",
) -> Optional[Transcript]:
    """
    Transcribe an audio file to a structured Transcript.

    Tries in order:
    1. faster-whisper (local, private, fast on M4 Pro with int8)
    2. mlx-whisper (Apple Silicon native — fastest if available)
    3. OpenAI Whisper API (cloud fallback)
    4. yt-dlp auto-subtitles (last resort — often available for popular videos)
    """
    if not audio_path.exists():
        log.error(f"Audio file not found: {audio_path}")
        return None

    vid = video_id or audio_path.stem
    log.info(f"Transcribing {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f}MB)")

    # Try faster-whisper first
    transcript = _transcribe_faster_whisper(audio_path, vid, language)
    if transcript:
        return transcript

    # Try mlx-whisper (Apple Silicon native)
    transcript = _transcribe_mlx_whisper(audio_path, vid, language)
    if transcript:
        return transcript

    # Cloud fallback: OpenAI Whisper API
    transcript = _transcribe_openai_api(audio_path, vid, language)
    if transcript:
        return transcript

    log.error(f"All transcription methods failed for {audio_path.name}")
    return None


def _transcribe_faster_whisper(
    audio_path: Path,
    video_id: str,
    language: str,
) -> Optional[Transcript]:
    """Transcribe using faster-whisper (CTranslate2 backend)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.debug("faster-whisper not installed — skipping")
        return None

    try:
        start = time.monotonic()
        model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )

        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=WHISPER_BEAM_SIZE,
            language=language,
            word_timestamps=False,
            vad_filter=True,  # Skip silence — faster + cleaner
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        segments = []
        for seg in segments_iter:
            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
            ))

        elapsed = time.monotonic() - start
        duration = segments[-1].end if segments else 0
        ratio = duration / elapsed if elapsed > 0 else 0
        log.info(
            f"faster-whisper: {len(segments)} segments, "
            f"{duration:.0f}s audio in {elapsed:.1f}s ({ratio:.1f}x realtime)"
        )

        return Transcript(
            video_id=video_id,
            segments=segments,
            language=info.language if hasattr(info, "language") else language,
            model_used=f"faster-whisper/{WHISPER_MODEL}",
        )

    except Exception as e:
        log.warning(f"faster-whisper failed: {e}")
        return None


def _transcribe_mlx_whisper(
    audio_path: Path,
    video_id: str,
    language: str,
) -> Optional[Transcript]:
    """Transcribe using mlx-whisper (Apple Silicon native via MLX)."""
    try:
        import mlx_whisper
    except ImportError:
        log.debug("mlx-whisper not installed — skipping")
        return None

    try:
        start = time.monotonic()
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=f"mlx-community/whisper-{WHISPER_MODEL}-mlx",
            language=language,
        )

        segments = []
        for seg in result.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))

        elapsed = time.monotonic() - start
        log.info(f"mlx-whisper: {len(segments)} segments in {elapsed:.1f}s")

        return Transcript(
            video_id=video_id,
            segments=segments,
            language=language,
            model_used=f"mlx-whisper/{WHISPER_MODEL}",
        )

    except Exception as e:
        log.warning(f"mlx-whisper failed: {e}")
        return None


def _transcribe_openai_api(
    audio_path: Path,
    video_id: str,
    language: str,
) -> Optional[Transcript]:
    """Transcribe using OpenAI Whisper API (cloud fallback)."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        log.debug("No OPENAI_API_KEY — skipping cloud transcription")
        return None

    try:
        import httpx
    except ImportError:
        log.debug("httpx not installed — skipping cloud transcription")
        return None

    # OpenAI Whisper API has a 25MB limit
    file_size = audio_path.stat().st_size
    if file_size > 25 * 1024 * 1024:
        log.warning(f"Audio file too large for OpenAI API ({file_size / 1024 / 1024:.1f}MB > 25MB)")
        return None

    try:
        start = time.monotonic()
        with open(audio_path, "rb") as f:
            response = httpx.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, f, "audio/mpeg")},
                data={
                    "model": "whisper-1",
                    "language": language,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                },
                timeout=300.0,
            )
            response.raise_for_status()

        data = response.json()
        segments = []
        for seg in data.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))

        elapsed = time.monotonic() - start
        log.info(f"OpenAI Whisper API: {len(segments)} segments in {elapsed:.1f}s")

        return Transcript(
            video_id=video_id,
            segments=segments,
            language=data.get("language", language),
            model_used="openai/whisper-1",
        )

    except Exception as e:
        log.warning(f"OpenAI Whisper API failed: {e}")
        return None


def transcribe_batch(
    audio_files: list[tuple[dict, Path]],
) -> list[tuple[dict, Transcript]]:
    """
    Transcribe a batch of (video_info, audio_path) tuples.

    Returns list of (video_info, transcript) for successful transcriptions.
    """
    results: list[tuple[dict, Transcript]] = []

    for video_info, audio_path in audio_files:
        vid = video_info.get("video_id", audio_path.stem)
        transcript = transcribe_audio(audio_path, video_id=vid)
        if transcript:
            results.append((video_info, transcript))
        else:
            log.warning(f"Transcription failed for {video_info.get('title', vid)}")

    log.info(f"Transcribed {len(results)}/{len(audio_files)} videos")
    return results
