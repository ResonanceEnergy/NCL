"""Weekly memory-eval scheduler loop (Loop 2).

Designed to be wired into ``runtime/autonomous/scheduler.py`` alongside the
other ``ncl-*`` loops. Cadence: Sunday 03:00 America/New_York.

On regression > 5% (any of hit@5/hit@10/MRR/recall@10) the loop enqueues
an ntfy alert via the centralized AlertDispatcher.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import MemoryEvalRunner

log = logging.getLogger("ncl.memory.eval.loop")

# Default cadence — weekly
WEEKLY_INTERVAL_S = 7 * 24 * 60 * 60  # 604_800


def _seconds_until_sunday_3am_et(now_utc: Optional[datetime] = None) -> float:
    """Return seconds until the next Sunday 03:00 in US/Eastern."""
    try:
        import pytz  # local import to keep the module importable in tests
    except Exception:
        # Fallback — schedule for 24h out if pytz missing.
        return 24 * 3600.0

    et = pytz.timezone("US/Eastern")
    now_et = (now_utc or datetime.now(timezone.utc)).astimezone(et)
    # weekday(): Mon=0 .. Sun=6
    days_ahead = (6 - now_et.weekday()) % 7
    target = (now_et + timedelta(days=days_ahead)).replace(
        hour=3, minute=0, second=0, microsecond=0
    )
    if target <= now_et:
        target += timedelta(days=7)
    return max(60.0, (target - now_et).total_seconds())


async def _memory_eval_loop(brain: Any) -> None:
    """Weekly memory eval loop. Spawn as ``asyncio.create_task(_memory_eval_loop(brain), name='ncl-memory-eval')``.

    The loop:
      1. Sleeps until the next Sunday 03:00 ET.
      2. Runs the full eval against ``brain.memory_store``.
      3. Diffs against the prior persisted run.
      4. Records ``last_memory_eval_at`` + ``last_memory_eval_result`` on the scheduler.
      5. Pushes an ntfy alert via the central AlertDispatcher on regression > 5%.
    """
    scheduler = getattr(brain, "scheduler", None)
    stats = getattr(scheduler, "_stats", None) if scheduler is not None else None

    # Lazy imports — keep this module importable outside the brain runtime.
    try:
        from ...notifications import enqueue_alert  # type: ignore
    except Exception:
        enqueue_alert = None  # type: ignore[assignment]

    log.info("[MEMORY-EVAL] Loop started — next fire = Sunday 03:00 ET")

    # Brief startup delay so we don't run during boot smoke.
    await asyncio.sleep(60)

    while True:
        try:
            sleep_s = _seconds_until_sunday_3am_et()
            log.info("[MEMORY-EVAL] Sleeping %.0fs until next Sunday 03:00 ET", sleep_s)
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            log.info("[MEMORY-EVAL] cancelled")
            raise

        # ── Run the eval ───────────────────────────────────────────
        try:
            memory_store = getattr(brain, "memory_store", None)
            if memory_store is None:
                log.error("[MEMORY-EVAL] brain has no memory_store — skipping cycle")
                await asyncio.sleep(3600)
                continue

            runner = MemoryEvalRunner(memory_store=memory_store)
            result = await runner.run_eval()
            diff = await runner.compare_to_baseline(current=result)

            agg = result.get("aggregate", {})
            log.info(
                "[MEMORY-EVAL] Run complete — hit@5=%.3f hit@10=%.3f mrr=%.3f recall@10=%.3f",
                agg.get("hit5", 0), agg.get("hit10", 0),
                agg.get("mrr", 0), agg.get("recall10", 0),
            )

            if stats is not None:
                stats["last_memory_eval_at"] = result["timestamp"]
                stats["last_memory_eval_result"] = {
                    "aggregate": agg,
                    "regression": diff.get("regression", False),
                    "deltas": diff.get("deltas", {}),
                    "baseline_date": diff.get("baseline_date"),
                }

            # ── Push alert on regression > 5% ──────────────────────
            if diff.get("regression"):
                title = "NCL Memory Eval Regression"
                worst = min(
                    diff.get("deltas", {}).items(),
                    key=lambda kv: kv[1],
                    default=("?", 0.0),
                )
                body = (
                    f"Memory retrieval regressed vs {diff.get('baseline_date')}:\n"
                    f"  hit@5  delta: {diff['deltas'].get('hit5', 0):+.3f}\n"
                    f"  hit@10 delta: {diff['deltas'].get('hit10', 0):+.3f}\n"
                    f"  MRR    delta: {diff['deltas'].get('mrr', 0):+.3f}\n"
                    f"  recall delta: {diff['deltas'].get('recall10', 0):+.3f}\n"
                    f"Worst metric: {worst[0]} ({worst[1]:+.3f})\n"
                    f"Threshold: -{runner.REGRESSION_THRESHOLD:.2f}"
                )
                if enqueue_alert is not None:
                    try:
                        enqueue_alert(
                            title=title,
                            body=body,
                            priority="4",
                            tags="brain,warning",
                            dedup_key=f"memory-eval:{result['date']}",
                            source="memory-eval",
                        )
                        log.warning("[MEMORY-EVAL] regression alert enqueued")
                    except Exception as e:
                        log.error("[MEMORY-EVAL] alert enqueue failed: %s", e)
                else:
                    log.warning("[MEMORY-EVAL] AlertDispatcher not importable — %s", body)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[MEMORY-EVAL] cycle error: %s", e, exc_info=True)
            # Don't spin forever on persistent failure
            await asyncio.sleep(3600)


__all__ = ["_memory_eval_loop", "WEEKLY_INTERVAL_S", "_seconds_until_sunday_3am_et"]
