"""
ncl-haiku-ab-monitor loop (carved from scheduler.py, W10A-11).

Daily (24h cadence) Haiku A/B test trailing summary writer. Cheap when
disabled (early-returns on `ab_test.is_ab_enabled() == False`); when
enabled, writes `data/memory/ab_test/daily-summary-YYYY-MM-DD.json` and
ntfys if disagreement crosses thresholds (p95_abs_delta > 2.0 or more
than 10 Haiku errors in window).

First write fires 1h post-boot so a same-day restart still produces a
summary; subsequent writes loop every 24h.

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler._running` (bool gate to stop the loop)

Other module-level dependencies:
- `runtime.memory.ab_test.is_ab_enabled` + `write_daily_summary`
- `runtime.notifications.alert_dispatch.enqueue_alert` (best-effort)

This module deliberately does NOT consult EMERGENCY_STOP_EVENT: the
inline closure that previously lived in scheduler.py also did not. The
A/B summary is a passive analytics write — gating it on emergency-stop
would prevent forensic capture of the last 24h when an incident is
being investigated. If that policy ever changes, add the check here.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging

log = logging.getLogger(__name__)

_BOOT_DELAY_S = 3600  # first cycle ~1h after boot
_DISABLED_RECHECK_S = 3600  # re-check the feature flag every hour while off
_CYCLE_S = 86400  # 24h between summaries


async def run(scheduler) -> None:
    """Run the Haiku A/B daily-summary loop for the given scheduler.

    The scheduler instance owns the lifecycle flag (`_running`). This
    function is the extracted body of what used to be
    `_haiku_ab_monitor_loop` defined inline inside `Scheduler.start()`.
    """
    from ...memory import ab_test as _ab

    # Wait 24h between writes; first write fires 1h post-boot so we
    # have something even on a same-day restart.
    await asyncio.sleep(_BOOT_DELAY_S)
    while scheduler._running:
        if not _ab.is_ab_enabled():
            await asyncio.sleep(_DISABLED_RECHECK_S)
            continue
        try:
            summary = _ab.write_daily_summary()
            log.info(
                "[AB-MONITOR] rows=%d paired=%d mean_delta=%.2f p95_delta=%.2f "
                "savings=%.1f%% recommendation=%s",
                summary.get("rows", 0),
                summary.get("rows_with_both_scores", 0),
                summary.get("mean_abs_delta", 0.0),
                summary.get("p95_abs_delta", 0.0),
                summary.get("savings_pct_if_switched", 0.0),
                summary.get("recommendation", "?"),
            )
            # Alert if Haiku diverges meaningfully or errors out.
            if summary.get("p95_abs_delta", 0.0) > 2.0 or summary.get("haiku_errors", 0) > 10:
                try:
                    from ...notifications.alert_dispatch import enqueue_alert

                    enqueue_alert(
                        title="Haiku A/B divergence",
                        body=(
                            f"p95_delta={summary.get('p95_abs_delta', 0):.2f} "
                            f"haiku_errors={summary.get('haiku_errors', 0)} "
                            f"rec={summary.get('recommendation', '?')}"
                        ),
                        priority="3",
                        dedup_key="haiku_ab_divergence",
                        source="memory",
                    )
                except Exception:
                    pass
        except Exception as e:
            log.warning("[AB-MONITOR] daily summary failed: %s", e)
        await asyncio.sleep(_CYCLE_S)
