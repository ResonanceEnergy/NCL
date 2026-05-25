"""
Process-wide singleton for the ``faster-whisper`` ``WhisperModel``.

Why this exists
---------------
Before this module, two call sites instantiated their own
``WhisperModel`` against the same on-disk model files:

* ``runtime/lde/ingestor.py::_try_faster_whisper`` — *fresh per audio
  file*, called for every URL the LDE ingests
* ``runtime/councils/youtube/transcriber.py`` already memoizes via a
  module-level ``_faster_whisper_model`` global — kept for back-compat,
  but new call sites should use this singleton

``WhisperModel.__init__()`` loads the CTranslate2 weights into memory
(~3GB for large-v3 / int8) and opens shared model handles. Multiple
short-lived models pointed at the same model dir can deadlock the
CTranslate2 backend's internal worker threads — the same class of bug
as the W12 ChromaDB Rust HNSW deadlock (fresh ``PersistentClient`` per
call against the same persistent store, observed 2026-05-24 19:20).

YTC runs ~33 videos/hour. Each transcription spawning a fresh model
also burns ~10s of CPU on weight loading before any work happens, plus
keeps two copies of the model resident if the GC hasn't reaped the
previous instance yet.

Public API
----------
``get_whisper_model(model_size, compute_type)`` returns a single shared
``WhisperModel``. First call constructs it; subsequent calls return the
already-constructed instance. Double-checked locking on an
``asyncio.Lock`` prevents two concurrent boots.

Callers MUST go through this function, not ``WhisperModel(...)``
directly. If the cfg passed on a later call diverges from the cfg the
singleton was built with we log a warning and reuse the existing
instance — the model is expensive to rebuild and a divergent cfg is
almost always a caller bug, not an intentional reconfiguration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any


log = logging.getLogger("ncl.lde.whisper_singleton")


_instance: Any | None = None
_lock: asyncio.Lock | None = None
_cfg_used: tuple[str, str, str] | None = None  # (model_size, device, compute_type)


def _get_lock() -> asyncio.Lock:
    """Lazily build the asyncio.Lock so it binds to the running event loop."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_whisper_model(
    model_size: str = "base",
    compute_type: str = "int8",
    device: str = "cpu",
) -> Any:
    """Return the process-wide ``WhisperModel`` singleton.

    Args:
        model_size: faster-whisper model identifier (e.g. ``"large-v3"``,
            ``"base"``). Used to seed the singleton on first call.
        compute_type: CTranslate2 compute type (e.g. ``"int8"``,
            ``"float16"``).
        device: ``"cpu"`` / ``"cuda"`` / ``"auto"``.

    Returns:
        The shared ``faster_whisper.WhisperModel`` instance.

    Raises:
        ImportError: if ``faster_whisper`` isn't installed. Callers
            should catch this and fall through to alternative backends
            (mlx-whisper, OpenAI cloud API).
    """
    global _instance, _cfg_used

    requested = (model_size, device, compute_type)

    if _instance is not None:
        # Hot path: instance already exists. No lock needed for the
        # read; Python attribute reads are atomic enough for this.
        if _cfg_used is not None and requested != _cfg_used:
            log.warning(
                "[WHISPER-SINGLETON] cfg mismatch — singleton was bound to %s, "
                "caller requested %s. Reusing existing singleton.",
                _cfg_used,
                requested,
            )
        return _instance

    async with _get_lock():
        # Re-check inside the lock (double-checked locking).
        if _instance is not None:
            return _instance

        from faster_whisper import WhisperModel  # local import — keeps the
        # singleton module importable even on machines without
        # faster-whisper installed, so callers can still try/except.

        log.info(
            "[WHISPER-SINGLETON] constructing WhisperModel(model_size=%s, device=%s, compute_type=%s)",  # noqa: E501
            model_size,
            device,
            compute_type,
        )
        # WhisperModel.__init__ does heavy work (weight load); run in
        # a worker thread so the event loop stays responsive. The
        # subsequent .transcribe() calls are still sync; callers wrap
        # them with asyncio.to_thread at their own discretion.
        loop = asyncio.get_event_loop()
        model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(model_size, device=device, compute_type=compute_type),
        )
        log.info("[WHISPER-SINGLETON] WhisperModel ready")

        _instance = model
        _cfg_used = requested
        return _instance


def reset_for_tests() -> None:
    """Drop the cached instance. Test-only — never call in prod."""
    global _instance, _cfg_used
    _instance = None
    _cfg_used = None
