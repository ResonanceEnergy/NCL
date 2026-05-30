"""Wave 14AP (2026-05-30) — Voice journaling via mlx-whisper + pyannote.

Note: WhisperX itself doesn't yet ship Python 3.14 wheels (released
versions all require <3.14). This module composes the same capability
out of the parts that DO work on Py3.14:

  - mlx-whisper (already installed, MLX-native, MPS-accelerated)
    for transcription with word-level timestamps
  - pyannote-audio 4.0 for speaker diarization
  - simple time-alignment merge to attach speaker labels to whisper
    segments by overlap

Output shape mirrors what WhisperX would have produced:
  {
    "text": "...",
    "language": "en",
    "duration_s": 42.1,
    "segments": [
        {"start": 0.0, "end": 4.3, "text": "...", "speaker": "SPEAKER_00"},
        ...
    ],
    "speakers": ["SPEAKER_00", "SPEAKER_01"],
    "model": "mlx-whisper:large-v3 + pyannote:3.1",
  }

Use this from the iOS audio-upload endpoint (added in a later wave)
to attach speaker-tagged transcripts to journal entries.

Dependencies (all installed in Wave 14AF+14AP):
  - mlx-whisper (already running via runtime/lde/ingestor.py)
  - pyannote.audio 4.0.4

HF token requirement: pyannote 3.1 ships the diarization pipeline
behind a gated model card. Set HF_TOKEN env var with a token that
has accepted the model terms. Falls through with diarization=[] when
no token is provided.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.journal.voice_transcribe")


# ── Module-level lazy caches ─────────────────────────────────────────

_DIARIZATION_PIPELINE = None
_DIARIZATION_LOAD_ATTEMPTED = False
_DIARIZATION_MODEL = os.getenv(
    "NCL_DIARIZATION_MODEL",
    "pyannote/speaker-diarization-3.1",
)
_WHISPER_MODEL = os.getenv(
    "NCL_WHISPER_MODEL",
    "mlx-community/whisper-large-v3-mlx",
)


def _load_diarization_pipeline():
    """Lazy-load pyannote diarization pipeline. Cached. Returns None on failure."""
    global _DIARIZATION_PIPELINE, _DIARIZATION_LOAD_ATTEMPTED
    if _DIARIZATION_PIPELINE is not None:
        return _DIARIZATION_PIPELINE
    if _DIARIZATION_LOAD_ATTEMPTED:
        return None
    _DIARIZATION_LOAD_ATTEMPTED = True

    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not hf_token:
        log.info("[voice] pyannote diarization needs HF_TOKEN — skipping (transcription will be untagged)")
        return None
    try:
        from pyannote.audio import Pipeline  # type: ignore
    except ImportError as e:
        log.warning("[voice] pyannote.audio not installed: %s", e)
        return None
    try:
        pipeline = Pipeline.from_pretrained(_DIARIZATION_MODEL, use_auth_token=hf_token)
        # Move to MPS for Apple-Silicon acceleration when possible.
        try:
            import torch  # type: ignore

            if torch.backends.mps.is_available():
                pipeline.to(torch.device("mps"))
        except Exception:
            pass
        _DIARIZATION_PIPELINE = pipeline
        log.info("[voice] pyannote diarization loaded: %s", _DIARIZATION_MODEL)
        return pipeline
    except Exception as e:
        log.warning("[voice] pyannote diarization load failed: %s", e)
        return None


# ── Public API ────────────────────────────────────────────────────────


async def transcribe_with_diarization(
    audio_path: Path | str,
    *,
    language: Optional[str] = None,
    min_speakers: int = 1,
    max_speakers: int = 4,
) -> dict:
    """Transcribe an audio file and attach speaker labels.

    Args:
        audio_path: filesystem path to a .wav / .mp3 / .m4a file.
        language: optional ISO 639-1 hint for the whisper backend.
        min_speakers / max_speakers: diarization constraints.

    Returns the canonical output shape documented at module level.
    Returns {"error": ..., "segments": []} on failure modes that
    yield no usable output.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return {"error": f"file not found: {audio_path}", "segments": []}

    # Transcription via the existing mlx-whisper path NCL already uses.
    transcription = await asyncio.to_thread(_run_mlx_whisper, audio_path, language)
    if not transcription:
        return {"error": "transcription failed", "segments": []}

    segments = transcription.get("segments") or []
    if not segments:
        return {**transcription, "speakers": [], "segments": []}

    # Diarization — runs only if pyannote model can be loaded.
    diar_segments = await asyncio.to_thread(_run_diarization, audio_path, min_speakers, max_speakers)
    if diar_segments:
        _attach_speakers_to_segments(segments, diar_segments)
        speakers = sorted({s.get("speaker") for s in segments if s.get("speaker")})
    else:
        speakers = []

    return {
        "text": transcription.get("text", ""),
        "language": transcription.get("language", language or "en"),
        "duration_s": transcription.get("duration_s", 0.0),
        "segments": segments,
        "speakers": speakers,
        "model": (
            f"mlx-whisper:{_WHISPER_MODEL.split('/')[-1]}"
            + (f" + pyannote:{_DIARIZATION_MODEL.split('/')[-1]}" if speakers else "")
        ),
    }


# ── Internals ────────────────────────────────────────────────────────


def _run_mlx_whisper(audio_path: Path, language: Optional[str]) -> Optional[dict]:
    try:
        import mlx_whisper  # type: ignore
    except ImportError as e:
        log.warning("[voice] mlx-whisper not installed: %s", e)
        return None
    try:
        kwargs = {"word_timestamps": True}
        if language:
            kwargs["language"] = language
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=_WHISPER_MODEL,
            **kwargs,
        )
    except Exception as e:
        log.warning("[voice] mlx-whisper transcribe failed: %s", e)
        return None
    segments = []
    for s in result.get("segments", []) or []:
        segments.append(
            {
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": str(s.get("text", "")).strip(),
                "words": s.get("words") or [],
            }
        )
    duration = 0.0
    if segments:
        duration = max(s["end"] for s in segments)
    return {
        "text": str(result.get("text", "")).strip(),
        "language": str(result.get("language", language or "en")),
        "duration_s": round(duration, 2),
        "segments": segments,
    }


def _run_diarization(
    audio_path: Path, min_speakers: int, max_speakers: int
) -> Optional[list[dict]]:
    pipeline = _load_diarization_pipeline()
    if pipeline is None:
        return None
    try:
        diar = pipeline(str(audio_path), min_speakers=min_speakers, max_speakers=max_speakers)
    except Exception as e:
        log.warning("[voice] diarization failed: %s", e)
        return None
    out: list[dict] = []
    try:
        for turn, _, speaker in diar.itertracks(yield_label=True):
            out.append({"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)})
    except Exception as e:
        log.warning("[voice] diarization parse failed: %s", e)
        return None
    return out


def _attach_speakers_to_segments(
    segments: list[dict], diar_segments: list[dict]
) -> None:
    """Mutate `segments` in-place — attach 'speaker' to each whisper segment.

    Picks the speaker whose timestamp range overlaps the most with the
    whisper segment's timestamps.
    """
    for seg in segments:
        s_start, s_end = float(seg["start"]), float(seg["end"])
        best_speaker = None
        best_overlap = 0.0
        for d in diar_segments:
            d_start, d_end = float(d["start"]), float(d["end"])
            overlap = max(0.0, min(s_end, d_end) - max(s_start, d_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = d["speaker"]
        if best_speaker:
            seg["speaker"] = best_speaker


__all__ = ["transcribe_with_diarization"]
