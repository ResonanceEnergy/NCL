"""
ncl-startup-migrations one-shot (carved from scheduler.py, W10A-11).

Fires 90s post-boot and runs two idempotent endpoint handlers that used
to be manual POSTs after every config change:
  1. `/memory/kg-cleanup`      — purge URL/domain noise nodes
  2. `/memory/retag-authority` — re-stamp existing units to the current
                                  authority map (entity_extractor +
                                  authority.py blacklist drift)

Both are cheap when nothing's drifted, corrective when it has. The
authority retag is the slower of the two (full pass over ~14K units in
3-4 min) and gets a 600s budget; the prior 180s budget was hitting
`asyncio.TimeoutError` post-W5-04. The kg-cleanup gets 60s.

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler._running` (bool gate to short-circuit if shutdown wins
  the race)
- `scheduler._stats` (mutated with `last_kg_cleanup_at`,
  `last_kg_cleanup_result`, `last_authority_retag_at`,
  `last_authority_retag_result`)

Other dependencies:
- `runtime.governance.emergency_stop.EMERGENCY_STOP_EVENT` — bail if
  the kill-switch is engaged at boot
- `scheduler.brain.memory_store._knowledge_graph` — for `cleanup_blacklisted()`
- `runtime.memory.authority.retag_authority_tiers` — for the retag pass

Both migrations call the underlying functions directly via
`scheduler.brain.memory_store` rather than the FastAPI route handlers.
Prior versions called `kg_cleanup_endpoint(authorization=Bearer ...)`,
which silently broke when W10C converted those handlers to use
`Depends(verify_strike_token_dep)` — `authorization` was no longer a
parameter, so every boot just logged `unexpected keyword argument
'authorization'` and skipped both migrations. Fixed 2026-05-25.

This is a one-shot rather than a periodic loop: the function returns
after both migrations complete (or are skipped) and the supervisor
treats a clean exit as terminal — no restart.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
from datetime import datetime, timezone

from ...governance.emergency_stop import EMERGENCY_STOP_EVENT

log = logging.getLogger(__name__)

_BOOT_DELAY_S = 90
_KG_CLEANUP_TIMEOUT_S = 60
_RETAG_TIMEOUT_S = 600  # ~3-4 min for 14K units, 600s headroom


async def run(scheduler) -> None:
    """Run the startup-migrations one-shot for the given scheduler.

    The scheduler instance owns the lifecycle flag (`_running`) and the
    stats dict (`_stats`) the migrations annotate. This function is the
    extracted body of what used to be `_startup_migrations` defined
    inline inside `Scheduler.start()`.
    """
    # Wait 90s so Brain is fully booted (Awarebot warmed, routes registered)
    await asyncio.sleep(_BOOT_DELAY_S)
    if not scheduler._running or EMERGENCY_STOP_EVENT.is_set():
        return
    log.info("[STARTUP-MIGRATIONS] Running idempotent post-boot migrations")
    # 2026-05-25: rewritten to call the underlying memory-store/KG functions
    # directly instead of the FastAPI route handlers.
    #
    # Background: W10C converted the memory router from `authorization:
    # str = Header(None)` to `_: None = Depends(verify_strike_token_dep)`.
    # The old `kg_cleanup_endpoint(authorization=bearer)` /
    # `retag_authority_endpoint(authorization=bearer)` kwarg calls began
    # silently failing with `unexpected keyword argument 'authorization'`
    # on every boot — visible in logs as
    # `[STARTUP-MIGRATIONS] KG cleanup skipped: ...` /
    # `Authority retag skipped: ...`. Both migrations had been no-ops for
    # weeks until this fix.
    #
    # Fix: skip the HTTP-style call entirely. The route handlers are thin
    # wrappers around `kg.cleanup_blacklisted()` and
    # `retag_authority_tiers(store)`; call those directly via
    # `scheduler.brain` so there's no auth surface to satisfy in the first
    # place. Bonus: avoids the FastAPI Depends() machinery being invoked
    # from a non-request context.
    brain = getattr(scheduler, "brain", None)
    if brain is None or getattr(brain, "memory_store", None) is None:
        log.warning("[STARTUP-MIGRATIONS] Brain or memory_store unavailable — skipping migrations")
        log.info("[STARTUP-MIGRATIONS] Complete")
        return

    # ── KG cleanup ── purge URL/domain noise nodes ───────────────────────
    try:
        kg = getattr(brain.memory_store, "_knowledge_graph", None) or getattr(
            brain, "knowledge_graph", None
        )
        if kg is None:
            log.warning("[STARTUP-MIGRATIONS] KG cleanup skipped: knowledge graph not initialized")
        else:
            result = await asyncio.wait_for(
                kg.cleanup_blacklisted(),
                timeout=_KG_CLEANUP_TIMEOUT_S,
            )
            scheduler._stats["last_kg_cleanup_at"] = datetime.now(timezone.utc).isoformat()
            scheduler._stats["last_kg_cleanup_result"] = str(result)[:200]
            log.info(f"[STARTUP-MIGRATIONS] KG cleanup: {str(result)[:200]}")
    except asyncio.TimeoutError:
        log.warning(f"[STARTUP-MIGRATIONS] KG cleanup exceeded {_KG_CLEANUP_TIMEOUT_S}s budget")
    except Exception as e:
        log.warning(f"[STARTUP-MIGRATIONS] KG cleanup failed: {type(e).__name__}: {e}")

    # ── Authority retag ── re-stamp units against the current map ─────────
    # Budget 600s: with ~14K units the full pass takes ~3-4 min, and the
    # operation is idempotent + read-mostly so a generous budget is safe.
    # 180s was hitting asyncio.TimeoutError post-W5-04.
    try:
        from ...memory.authority import retag_authority_tiers

        result = await asyncio.wait_for(
            retag_authority_tiers(brain.memory_store),
            timeout=_RETAG_TIMEOUT_S,
        )
        scheduler._stats["last_authority_retag_at"] = datetime.now(timezone.utc).isoformat()
        scheduler._stats["last_authority_retag_result"] = str(result)[:200]
        log.info(f"[STARTUP-MIGRATIONS] Authority retag: {str(result)[:200]}")
    except asyncio.TimeoutError:
        log.warning(
            "[STARTUP-MIGRATIONS] Authority retag exceeded 600s budget — see _stats next boot"  # noqa: E501
        )
    except Exception as e:
        log.warning(f"[STARTUP-MIGRATIONS] Authority retag failed: {type(e).__name__}: {e}")

    log.info("[STARTUP-MIGRATIONS] Complete")
