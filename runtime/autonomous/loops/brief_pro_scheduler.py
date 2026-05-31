"""Wave 14H — Morning Brief Pro scheduler.

Runs three jobs on the autonomous scheduler:
    02:30 ET — ncl-brief-prep    (collect overnight data)
    05:00 ET — ncl-brief-council (multi-LLM research)
    05:30 ET — ncl-brief-render  (presentation)

If a prior stage fails, downstream stages fall back gracefully:
    council with no prep   → uses last-good prep pack from yesterday
    render with no council → falls back to Phase 14D pipeline (existing)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

log = logging.getLogger("ncl.autonomous.brief_pro_scheduler")

ET = ZoneInfo("America/New_York")
NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
STATE_PATH = NCL_BASE / "data" / "morning-brief-pro" / "scheduler-state.json"

# Local-time targets in America/New_York
PREP_TARGET_ET = time(hour=2, minute=30)
COUNCIL_TARGET_ET = time(hour=5, minute=0)
RENDER_TARGET_ET = time(hour=5, minute=30)


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def _seconds_until(target_et: time, now_utc: datetime) -> float:
    """Seconds from now to the next occurrence of target_et in America/New_York."""
    now_et = now_utc.astimezone(ET)
    today_target = now_et.replace(
        hour=target_et.hour, minute=target_et.minute, second=0, microsecond=0
    )
    if today_target <= now_et:
        today_target += timedelta(days=1)
    return (today_target - now_et).total_seconds()


async def _run_prep(brain) -> bool:
    try:
        from runtime.intelligence.brief_prep import build_prep_pack
        log.info("[brief-pro] PREP stage starting")
        pack = await build_prep_pack(brain)
        log.info("[brief-pro] PREP stage complete: %s blocks, %.1fs",
                 sum(1 for v in pack.values() if v), pack.get("elapsed_s", 0))
        return True
    except Exception as e:
        log.warning("[brief-pro] PREP stage failed: %s", e)
        return False


async def _run_council() -> bool:
    try:
        from runtime.intelligence.brief_prep import load_latest_prep_pack
        from runtime.intelligence.brief_council import run_council
        pack = load_latest_prep_pack()
        if pack is None:
            log.warning("[brief-pro] COUNCIL stage: no prep pack — aborting")
            return False
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.warning("[brief-pro] COUNCIL stage: ANTHROPIC_API_KEY not set")
            return False
        log.info("[brief-pro] COUNCIL stage starting (4 members + chair)")
        await run_council(pack, api_key=api_key)
        log.info("[brief-pro] COUNCIL stage complete")
        return True
    except Exception as e:
        log.warning("[brief-pro] COUNCIL stage failed: %s", e)
        return False


async def _run_render(brain=None) -> bool:
    try:
        from runtime.intelligence.brief_archiver import archive_brief
        from runtime.intelligence.brief_council import load_latest_council
        from runtime.intelligence.brief_presenter import render_pro_brief
        from runtime.intelligence.brief_prep import load_latest_prep_pack
        council = load_latest_council()
        if council is None:
            log.warning("[brief-pro] RENDER stage: no council output — aborting")
            return False
        pack = load_latest_prep_pack()
        synthesis = council.get("synthesis") or council
        envelope = render_pro_brief(synthesis, pack=pack)
        # Wave 14CQ — same archive close-loop as /morning-brief/pro/fire.
        # Materializes .md, snapshots to memory, registers trade_ideas
        # with trade_idea_tracker so the auto-trader actually sees them.
        try:
            archive_result = await archive_brief(
                envelope, pack=pack, mode="am", brain=brain,
            )
            log.info("[brief-pro] archive complete: %s", archive_result)
        except Exception as e:
            log.warning("[brief-pro] archive failed: %s", e)
        log.info("[brief-pro] RENDER stage complete")
        return True
    except Exception as e:
        log.warning("[brief-pro] RENDER stage failed: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────
# Loop entry points — three separate loops so scheduler can throttle each
# ─────────────────────────────────────────────────────────────────────────


async def brief_prep_loop(brain) -> None:
    """02:30 ET nightly — prep stage."""
    log.info("[brief-pro] prep loop started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            sleep_s = _seconds_until(PREP_TARGET_ET, now)
            log.info("[brief-pro] prep next run in %.0fs (target 02:30 ET)", sleep_s)
            await asyncio.sleep(sleep_s)
            ok = await _run_prep(brain)
            state = _load_state()
            state["last_prep_at"] = datetime.now(timezone.utc).isoformat()
            state["last_prep_ok"] = ok
            _save_state(state)
        except asyncio.CancelledError:
            log.info("[brief-pro] prep loop cancelled")
            return
        except Exception as e:
            log.warning("[brief-pro] prep loop error: %s", e)
            await asyncio.sleep(300)


async def brief_council_loop(brain) -> None:
    """05:00 ET nightly — council stage."""
    log.info("[brief-pro] council loop started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            sleep_s = _seconds_until(COUNCIL_TARGET_ET, now)
            log.info("[brief-pro] council next run in %.0fs (target 05:00 ET)", sleep_s)
            await asyncio.sleep(sleep_s)
            ok = await _run_council()
            state = _load_state()
            state["last_council_at"] = datetime.now(timezone.utc).isoformat()
            state["last_council_ok"] = ok
            _save_state(state)
        except asyncio.CancelledError:
            log.info("[brief-pro] council loop cancelled")
            return
        except Exception as e:
            log.warning("[brief-pro] council loop error: %s", e)
            await asyncio.sleep(300)


async def brief_render_loop(brain) -> None:
    """05:30 ET nightly — render stage."""
    log.info("[brief-pro] render loop started")
    while True:
        try:
            now = datetime.now(timezone.utc)
            sleep_s = _seconds_until(RENDER_TARGET_ET, now)
            log.info("[brief-pro] render next run in %.0fs (target 05:30 ET)", sleep_s)
            await asyncio.sleep(sleep_s)
            ok = await _run_render(brain=brain)
            state = _load_state()
            state["last_render_at"] = datetime.now(timezone.utc).isoformat()
            state["last_render_ok"] = ok
            _save_state(state)
        except asyncio.CancelledError:
            log.info("[brief-pro] render loop cancelled")
            return
        except Exception as e:
            log.warning("[brief-pro] render loop error: %s", e)
            await asyncio.sleep(300)
