"""
YouTube Council — Audio Transcriber

Transcribes audio files using faster-whisper, optimized for Apple Silicon.
Falls back to OpenAI Whisper API if local model unavailable.

Mac Mini M4 Pro: Uses CPU with int8 quantization for good speed/quality balance.
For even faster inference, install mlx-whisper (Apple Silicon native).
"""

from __future__ import annotations

import json
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

# Transcript cache dir — same as audio cache, stores .transcript.json alongside .mp3
_TRANSCRIPT_CACHE_DIR = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / ".cache" / "youtube-audio"

# Audio cleanup: delete audio files older than this many days
_AUDIO_MAX_AGE_DAYS = int(os.getenv("YTC_AUDIO_MAX_AGE_DAYS", "14"))


def _transcript_cache_path(video_id: str) -> Path:
    """Return the cache path for a transcript JSON."""
    return _TRANSCRIPT_CACHE_DIR / f"{video_id}.transcript.json"


def _load_cached_transcript(video_id: str) -> Optional[Transcript]:
    """Load a previously cached transcript if available."""
    cache_file = _transcript_cache_path(video_id)
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        segments = [
            TranscriptSegment(
                start=s["start"], end=s["end"], text=s["text"],
            )
            for s in data.get("segments", [])
        ]
        transcript = Transcript(
            video_id=data.get("video_id", video_id),
            segments=segments,
            language=data.get("language", "en"),
            model_used=data.get("model_used", "cached"),
        )
        log.info(f"Transcript cache hit: {video_id} ({len(segments)} segments)")
        return transcript
    except Exception as e:
        log.warning(f"Failed to load cached transcript for {video_id}: {e}")
        return None


def _save_transcript_cache(video_id: str, transcript: Transcript) -> None:
    """Save transcript to cache for future reuse."""
    cache_file = _transcript_cache_path(video_id)
    try:
        _TRANSCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "video_id": transcript.video_id,
            "language": transcript.language,
            "model_used": transcript.model_used,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in transcript.segments
            ],
            "cached_at": time.time(),
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        log.info(f"Transcript cached: {video_id}")
    except Exception as e:
        log.warning(f"Failed to cache transcript for {video_id}: {e}")


def cleanup_old_audio(max_age_days: int = _AUDIO_MAX_AGE_DAYS) -> int:
    """Delete audio files older than max_age_days. Returns count of deleted files."""
    if not _TRANSCRIPT_CACHE_DIR.exists():
        return 0
    cutoff = time.time() - (max_age_days * 86400)
    deleted = 0
    audio_extensions = {".mp3", ".mp4", ".webm", ".m4a", ".opus", ".ogg", ".wav"}
    for f in _TRANSCRIPT_CACHE_DIR.iterdir():
        if f.suffix in audio_extensions and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
    if deleted:
        log.info(f"Audio cleanup: deleted {deleted} files older than {max_age_days} days")
    return deleted


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

    # Check transcript cache first — avoids re-transcribing on repeat runs
    cached = _load_cached_transcript(vid)
    if cached:
        return cached

    log.info(f"Transcribing {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f}MB)")

    # Try faster-whisper first
    transcript = _transcribe_faster_whisper(audio_path, vid, language)
    if transcript:
        _save_transcript_cache(vid, transcript)
        return transcript

    # Try mlx-whisper (Apple Silicon native)
    transcript = _transcribe_mlx_whisper(audio_path, vid, language)
    if transcript:
        _save_transcript_cache(vid, transcript)
        return transcript

    # Cloud fallback: OpenAI Whisper API
    transcript = _transcribe_openai_api(audio_path, vid, language)
    if transcript:
        _save_transcript_cache(vid, transcript)
        return transcript

    log.error(f"All transcription methods failed for {audio_path.name}")
    return None


# Module-level cache for Whisper models (load once, reuse across calls)
_faster_whisper_model = None
_mlx_whisper_available: Optional[bool] = None


def _get_faster_whisper_model():
    """Get or create the cached faster-whisper model instance."""
    global _faster_whisper_model
    if _faster_whisper_model is not None:
        return _faster_whisper_model
    from faster_whisper import WhisperModel
    _faster_whisper_model = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )
    log.info(f"faster-whisper model loaded: {WHISPER_MODEL} ({WHISPER_DEVICE}/{WHISPER_COMPUTE_TYPE})")
    return _faster_whisper_model


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
        model = _get_faster_whisper_model()

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


def _split_audio_for_api(audio_path: Path, max_size_mb: float = 24.0) -> list[Path]:
    """Split audio file into chunks under the OpenAI 25MB limit using ffmpeg.

    Uses segment duration estimation: computes bitrate from file, then picks
    a chunk duration that keeps each piece under max_size_mb. Returns list of
    chunk file paths (caller should clean up after use).
    """
    import subprocess
    import math

    file_size = audio_path.stat().st_size
    max_bytes = int(max_size_mb * 1024 * 1024)

    if file_size <= max_bytes:
        return [audio_path]  # No splitting needed

    ffmpeg = "/opt/homebrew/bin/ffmpeg"

    # Get duration via ffprobe
    try:
        probe = subprocess.run(
            [ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "quiet", "-show_entries",
             "format=duration", "-of", "csv=p=0", str(audio_path)],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(probe.stdout.strip())
    except Exception:
        duration = 3600.0  # Assume 1h fallback

    # Calculate chunk duration to stay under max_size_mb
    bitrate = file_size / duration  # bytes per second
    chunk_duration = int(max_bytes / bitrate * 0.9)  # 90% safety margin
    chunk_duration = max(chunk_duration, 60)  # At least 60 seconds

    num_chunks = math.ceil(duration / chunk_duration)
    log.info(f"Splitting {audio_path.name} ({file_size / 1024 / 1024:.1f}MB, {duration:.0f}s) "
             f"into ~{num_chunks} chunks of {chunk_duration}s each")

    chunks: list[Path] = []
    chunk_dir = audio_path.parent / f"_chunks_{audio_path.stem}"
    chunk_dir.mkdir(exist_ok=True)

    try:
        result = subprocess.run(
            [ffmpeg, "-i", str(audio_path), "-f", "segment",
             "-segment_time", str(chunk_duration), "-c", "copy",
             "-reset_timestamps", "1", "-y",
             str(chunk_dir / f"chunk_%03d{audio_path.suffix}")],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning(f"ffmpeg split failed: {result.stderr[:300]}")
            return [audio_path]

        chunks = sorted(chunk_dir.glob(f"chunk_*{audio_path.suffix}"))
        log.info(f"Split into {len(chunks)} chunks")
        return chunks if chunks else [audio_path]

    except Exception as e:
        log.warning(f"Audio split failed: {e}")
        return [audio_path]


def _transcribe_openai_api(
    audio_path: Path,
    video_id: str,
    language: str,
) -> Optional[Transcript]:
    """Transcribe using OpenAI Whisper API (cloud fallback).

    For files > 25MB, splits audio into chunks with ffmpeg and transcribes
    each chunk separately, then merges the segments with corrected timestamps.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        log.debug("No OPENAI_API_KEY — skipping cloud transcription")
        return None

    try:
        import httpx
    except ImportError:
        log.debug("httpx not installed — skipping cloud transcription")
        return None

    file_size = audio_path.stat().st_size
    needs_split = file_size > 25 * 1024 * 1024

    if needs_split:
        chunks = _split_audio_for_api(audio_path)
        if len(chunks) == 1 and chunks[0] == audio_path:
            # Split failed and file is still too large — can't proceed
            if file_size > 25 * 1024 * 1024:
                log.warning(f"Audio file too large for OpenAI API ({file_size / 1024 / 1024:.1f}MB > 25MB) "
                            f"and splitting failed")
                return None
    else:
        chunks = [audio_path]

    try:
        import subprocess
        start = time.monotonic()
        all_segments: list[TranscriptSegment] = []
        time_offset = 0.0
        detected_language = language

        for chunk_idx, chunk_path in enumerate(chunks):
            # Get chunk duration for timestamp offset
            chunk_duration = 0.0
            try:
                probe = subprocess.run(
                    ["/opt/homebrew/bin/ffprobe", "-v", "quiet", "-show_entries",
                     "format=duration", "-of", "csv=p=0", str(chunk_path)],
                    capture_output=True, text=True, timeout=10,
                )
                chunk_duration = float(probe.stdout.strip())
            except Exception:
                chunk_duration = 600.0  # 10 min fallback

            log.info(f"Transcribing chunk {chunk_idx + 1}/{len(chunks)} "
                     f"({chunk_path.stat().st_size / 1024 / 1024:.1f}MB, offset={time_offset:.0f}s)")

            with open(chunk_path, "rb") as f:
                response = httpx.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (chunk_path.name, f, "audio/mpeg")},
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
            detected_language = data.get("language", detected_language)

            for seg in data.get("segments", []):
                all_segments.append(TranscriptSegment(
                    start=seg["start"] + time_offset,
                    end=seg["end"] + time_offset,
                    text=seg["text"].strip(),
                ))

            time_offset += chunk_duration

        elapsed = time.monotonic() - start
        log.info(f"OpenAI Whisper API: {len(all_segments)} segments in {elapsed:.1f}s "
                 f"({len(chunks)} chunk{'s' if len(chunks) > 1 else ''})")

        return Transcript(
            video_id=video_id,
            segments=all_segments,
            language=detected_language,
            model_used="openai/whisper-1",
        )

    except Exception as e:
        log.warning(f"OpenAI Whisper API failed: {e}")
        return None
    finally:
        # Clean up chunk files
        if needs_split:
            chunk_dir = audio_path.parent / f"_chunks_{audio_path.stem}"
            if chunk_dir.exists():
                import shutil
                try:
                    shutil.rmtree(chunk_dir)
                except Exception:
                    pass


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
