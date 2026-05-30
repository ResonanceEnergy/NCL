"""Wave 14BK — weekly BERTopic retrain loop.

Cadence: Sunday 04:00 America/New_York (1h after the memory-eval window
so we're not competing for CPU). Reads N days of agent_signals.jsonl,
buckets by source head, retrains all per-source BERTopic models that
have ≥ min_docs_per_source documents.

Wired into runtime/autonomous/scheduler.py as `ncl-bertopic-retrain`.

Also exposed at POST /system/bertopic/retrain so NATRIX can fire it
on demand from iOS or curl.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger("ncl.cross_reference.retrain")


# ── Knobs ─────────────────────────────────────────────────────────────

_DEFAULT_DAYS = int(os.getenv("NCL_BERTOPIC_RETRAIN_DAYS", "14"))
_DEFAULT_MIN_DOCS = int(os.getenv("NCL_BERTOPIC_RETRAIN_MIN_DOCS", "30"))
_DEFAULT_MIN_TOPIC = int(os.getenv("NCL_BERTOPIC_RETRAIN_MIN_TOPIC_SIZE", "5"))


# ── Time helper ───────────────────────────────────────────────────────


def _seconds_until_sunday_4am_et(now_utc: Optional[datetime] = None) -> float:
    """Seconds until the next Sunday 04:00 in US/Eastern. Mirrors
    runtime/memory/eval/loop._seconds_until_sunday_3am_et — bertopic
    retrain runs 1h after memory eval so they don't fight for CPU.
    """
    try:
        import pytz  # local — keep module importable in tests
    except Exception:
        return 24 * 3600.0

    et = pytz.timezone("US/Eastern")
    now_et = (now_utc or datetime.now(timezone.utc)).astimezone(et)
    days_ahead = (6 - now_et.weekday()) % 7
    target = (now_et + timedelta(days=days_ahead)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    if target <= now_et:
        target += timedelta(days=7)
    return max(60.0, (target - now_et).total_seconds())


# ── Signal loader (mirrors scripts/train_source_stratified_bertopic.py) ──


def _signal_log_path() -> Path:
    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    candidates = [
        base / "data" / "intelligence" / "agent_signals.jsonl",
        base / "data" / "agents" / "agent_signals.jsonl",
        base / "data" / "agent_signals.jsonl",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


def _load_signals_blocking(days: int) -> list[dict]:
    sig_log = _signal_log_path()
    if not sig_log.exists():
        log.warning("[bertopic-retrain] signal log not found at %s", sig_log)
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    out: list[dict] = []
    try:
        with sig_log.open() as fh:
            for raw in fh:
                try:
                    s = json.loads(raw)
                except Exception:
                    continue
                ts = s.get("timestamp") or s.get("created_at") or ""
                if ts and ts < cutoff_iso:
                    continue
                out.append(s)
    except Exception as e:
        log.warning("[bertopic-retrain] failed to read signal log: %s", e)
        return []
    return out


def _bucket_by_source(signals: list[dict]) -> dict[str, list[str]]:
    by_source: dict[str, list[str]] = defaultdict(list)
    for s in signals:
        head = (s.get("source", "") or "").split(":")[0].strip().lower()
        if not head:
            continue
        text = ((s.get("title") or "") + " " + (s.get("content") or "")).strip()
        if len(text) < 20:
            continue
        by_source[head].append(text)
    return dict(by_source)


# ── Public retrain entry-point — used by loop AND /system/bertopic/retrain ──


async def retrain_once(
    *,
    days: int = _DEFAULT_DAYS,
    min_docs_per_source: int = _DEFAULT_MIN_DOCS,
    min_topic_size: int = _DEFAULT_MIN_TOPIC,
) -> dict[str, Any]:
    """Single retrain cycle. Returns a structured result dict."""
    started = datetime.now(timezone.utc)
    signals = await asyncio.to_thread(_load_signals_blocking, days)
    n_signals = len(signals)
    if n_signals == 0:
        return {
            "status": "no_signals",
            "started_at": started.isoformat(),
            "days": days,
            "n_signals": 0,
            "trained": {},
            "skipped": {},
        }

    by_source = await asyncio.to_thread(_bucket_by_source, signals)
    per_source_counts = {k: len(v) for k, v in by_source.items()}
    log.info(
        "[bertopic-retrain] %d signals across %d sources: %s",
        n_signals,
        len(per_source_counts),
        ", ".join(f"{k}={v}" for k, v in sorted(per_source_counts.items(), key=lambda kv: -kv[1])),
    )

    from .bertopic_themes import train_source_stratified_bertopic

    # kwargs only — positional None on embed_model overrides the module
    # default and breaks SentenceTransformer(None).
    res = await asyncio.to_thread(
        lambda: train_source_stratified_bertopic(
            by_source,
            min_topic_size=min_topic_size,
            min_docs_per_source=min_docs_per_source,
        )
    )

    # Force a reload on the in-process cache so the new model takes
    # effect without a brain bounce.
    try:
        from . import _source_bertopic_loaded, _source_bertopic_lookup_attempted  # noqa
        import runtime.cross_reference as _xr

        _xr._source_bertopic_loaded = {}
        _xr._source_bertopic_lookup_attempted = False
    except Exception as e:
        log.debug("[bertopic-retrain] cache invalidation failed: %s", e)

    finished = datetime.now(timezone.utc)
    return {
        "status": "ok",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_s": round((finished - started).total_seconds(), 2),
        "days": days,
        "n_signals": n_signals,
        "per_source_counts": per_source_counts,
        "trained": res.get("trained", {}),
        "skipped": res.get("skipped", {}),
        "saved_to": res.get("saved_to"),
    }


# ── Scheduler loop ────────────────────────────────────────────────────


async def _bertopic_retrain_loop(brain: Any) -> None:
    """Weekly retrain loop. Spawn as
    asyncio.create_task(_bertopic_retrain_loop(brain), name='ncl-bertopic-retrain').
    """
    scheduler = getattr(brain, "scheduler", None)
    stats = getattr(scheduler, "_stats", None) if scheduler is not None else None
    log.info("[bertopic-retrain] loop started — next fire = Sun 04:00 ET")

    # Boot delay so we don't spin a 30s training run during startup.
    await asyncio.sleep(120)

    while True:
        try:
            sleep_s = _seconds_until_sunday_4am_et()
            log.info("[bertopic-retrain] sleeping %.0fs until next Sun 04:00 ET", sleep_s)
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            log.info("[bertopic-retrain] cancelled")
            raise

        try:
            result = await retrain_once()
            log.info(
                "[bertopic-retrain] cycle done — status=%s trained=%d skipped=%d elapsed=%ss",
                result.get("status"),
                len(result.get("trained", {})),
                len(result.get("skipped", {})),
                result.get("elapsed_s"),
            )
            if stats is not None:
                stats["last_bertopic_retrain_at"] = result.get("finished_at")
                stats["last_bertopic_retrain_result"] = {
                    "trained": {k: v.get("n_topics") for k, v in result.get("trained", {}).items()},
                    "n_signals": result.get("n_signals"),
                    "elapsed_s": result.get("elapsed_s"),
                }
        except Exception as e:
            log.exception("[bertopic-retrain] cycle failed: %s", e)
            await asyncio.sleep(3600)


__all__ = [
    "retrain_once",
    "_bertopic_retrain_loop",
    "_seconds_until_sunday_4am_et",
]
