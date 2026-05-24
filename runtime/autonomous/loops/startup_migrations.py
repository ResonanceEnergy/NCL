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
- `runtime.api.routers.memory.kg_cleanup_endpoint` +
  `retag_authority_endpoint` — invoked in-process (not via HTTP) using
  the `STRIKE_AUTH_TOKEN` env var for Bearer auth.

This is a one-shot rather than a periodic loop: the function returns
after both migrations complete (or are skipped) and the supervisor
treats a clean exit as terminal — no restart.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
import os
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
    # Call the endpoint handlers directly via the in-process app — same
    # path the /memory/kg-cleanup and /memory/retag-authority HTTP
    # routes use, but without going through the network. Idempotent —
    # the handlers do nothing if everything's already correctly tagged.
    try:
        # W5-04 moved these handlers from runtime.api.routes to
        # runtime.api.routers.memory and renamed them. Import from the
        # new home so the migrations actually run instead of warning.
        from ...api.routers.memory import (
            kg_cleanup_endpoint,
            retag_authority_endpoint,
        )

        token = os.environ.get("STRIKE_AUTH_TOKEN", "")
        bearer = f"Bearer {token}" if token else ""
        # KG cleanup — purge URL/domain noise nodes
        try:
            result = await asyncio.wait_for(
                kg_cleanup_endpoint(authorization=bearer),
                timeout=_KG_CLEANUP_TIMEOUT_S,
            )
            scheduler._stats["last_kg_cleanup_at"] = datetime.now(timezone.utc).isoformat()
            scheduler._stats["last_kg_cleanup_result"] = str(result)[:200]
            log.info(f"[STARTUP-MIGRATIONS] KG cleanup: {str(result)[:200]}")
        except Exception as e:
            log.warning(f"[STARTUP-MIGRATIONS] KG cleanup skipped: {e}")
        # Authority retag — re-stamps existing units to match current map.
        # Budget 600s: with ~14K units the full pass takes ~3-4 min, and
        # the operation is idempotent + read-mostly so a generous budget
        # is safe. 180s was hitting asyncio.TimeoutError post-W5-04.
        try:
            result = await asyncio.wait_for(
                retag_authority_endpoint(authorization=bearer),
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
            log.warning(f"[STARTUP-MIGRATIONS] Authority retag skipped: {type(e).__name__}: {e}")
    except Exception as e:
        log.warning(f"[STARTUP-MIGRATIONS] Memory router unavailable: {e}")
    log.info("[STARTUP-MIGRATIONS] Complete")
