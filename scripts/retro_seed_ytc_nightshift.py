#!/usr/bin/env python3
"""
W11-3 — Retro-seed YTC nightshift briefs.

The W11-1 nightshift loop fires at 3am LOCAL for *yesterday's* per-video
reports. It hasn't fired yet for 2026-05-22, 2026-05-23, or 2026-05-24,
so iOS Past Briefs has no history. This one-shot script calls
``run_youtube_nightshift(date_str)`` for each of those dates and writes
``nightshift-brief.{json,md}`` into the matching per-date folder —
mirroring the on-disk shape that the scheduler loop produces (see
``runtime/autonomous/scheduler.py::_ytc_nightshift_loop``) so the
existing ``/youtube/nightshift/*`` endpoints pick them up unmodified.

Idempotent — skips any date whose ``nightshift-brief.json`` already
exists.

Usage:
    python3 /Users/natrix/dev/NCL/scripts/retro_seed_ytc_nightshift.py

Cost: ~$0.30 Sonnet input per date (one synthesize_rollup() call per
day). Total budgeted at ~$0.90 for the 3 days.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Path bootstrap so we can import runtime.* without installing ────────
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
if str(NCL_BASE) not in sys.path:
    sys.path.insert(0, str(NCL_BASE))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("ncl.scripts.retro_seed_ytc_nightshift")


# Dates to retro-seed, in chronological order.
TARGET_DATES: tuple[str, ...] = (
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
    "2026-05-23",
    "2026-05-24",
)

# Estimated Sonnet rollup cost per date (matches the scheduler's record_cost).
EST_COST_PER_DATE_USD: float = 0.30


def _per_video_report_count(date_dir: Path) -> int:
    """Count per-video report JSONs in ``date_dir``, excluding our own outputs."""
    if not date_dir.exists():
        return 0
    count = 0
    for f in date_dir.glob("*.json"):
        if f.name.startswith("nightshift-brief"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Only consider per_video reports (skip stray rollups if any).
        rtype = data.get("report_type")
        if rtype and rtype != "per_video":
            continue
        count += 1
    return count


async def _seed_one_date(date_str: str) -> dict:
    """Run ``run_youtube_nightshift`` for ``date_str`` and persist the brief.

    Returns a stats dict suitable for the final summary print:
        {date, status, per_video_reports, insights, cost_usd, brief_path}
    where ``status`` is one of: ``written`` | ``skipped_existing`` |
    ``skipped_no_reports`` | ``skipped_insufficient`` | ``error``.
    """
    from runtime.councils.runner import run_youtube_nightshift  # type: ignore
    from runtime.councils.shared.report_writer import REPORTS_DIR  # type: ignore

    date_dir = REPORTS_DIR / "youtube" / date_str
    brief_path = date_dir / "nightshift-brief.json"
    pv_count = _per_video_report_count(date_dir)

    stats = {
        "date": date_str,
        "status": "error",
        "per_video_reports": pv_count,
        "insights": 0,
        "cost_usd": 0.0,
        "brief_path": str(brief_path),
    }

    if brief_path.exists():
        log.info(
            "[%s] nightshift-brief.json already present — skipping (idempotent)",
            date_str,
        )
        stats["status"] = "skipped_existing"
        return stats

    if pv_count == 0:
        log.warning(
            "[%s] no per-video reports found under %s — skipping",
            date_str,
            date_dir,
        )
        stats["status"] = "skipped_no_reports"
        return stats

    if pv_count < 2:
        # ``run_youtube_nightshift`` itself enforces >=2, but call out the
        # reason up front so the operator log makes sense.
        log.warning(
            "[%s] only %d per-video report — synthesizer requires >=2, skipping",
            date_str,
            pv_count,
        )
        stats["status"] = "skipped_insufficient"
        return stats

    session_id = (
        f"ytc-nightshift-{date_str}-retroseed-"
        f"{datetime.now(timezone.utc).strftime('%H%M%S')}"
    )
    log.info(
        "[%s] synthesizing rollup from %d per-video reports as %s",
        date_str,
        pv_count,
        session_id,
    )

    try:
        rollup = await run_youtube_nightshift(date_str, session_id)
    except Exception as e:
        log.error("[%s] run_youtube_nightshift failed: %s", date_str, e, exc_info=True)
        return stats

    if rollup is None:
        log.warning("[%s] synthesizer returned None — nothing written", date_str)
        stats["status"] = "skipped_insufficient"
        return stats

    # ── Persist nightshift-brief.json (mirror scheduler's shape) ────────
    date_dir.mkdir(parents=True, exist_ok=True)
    brief_data = rollup.to_dict()
    brief_data.update(
        {
            "session_id": session_id,
            "status": "complete",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "auto_triggered": False,
            "report_type": "nightshift_rollup",
            "rolled_up_date": date_str,
            "spawned_by": "scripts/retro_seed_ytc_nightshift.py",
        }
    )
    brief_tmp = brief_path.with_suffix(".json.tmp")
    brief_tmp.write_text(json.dumps(brief_data, default=str, indent=2), encoding="utf-8")
    brief_tmp.replace(brief_path)
    log.info("[%s] wrote %s", date_str, brief_path)

    # ── Persist nightshift-brief.md (human-readable, mirrors scheduler) ─
    md_lines: list[str] = []
    md_lines.append(f"# YouTube Council — Nightshift Brief ({date_str})\n")
    md_lines.append(f"_Session: {session_id}_\n")
    md_lines.append(f"_Synthesized: {datetime.now(timezone.utc).isoformat()}_\n\n")
    md_lines.append(f"**Per-video reports rolled up:** {rollup.sources_processed}  \n")
    md_lines.append(f"**Total content duration:** {rollup.total_duration_hours:.1f}h  \n")
    md_lines.append(f"**Insight count:** {len(rollup.insights)}  \n\n")
    if rollup.summary:
        md_lines.append("## Executive Summary\n\n")
        md_lines.append(rollup.summary + "\n\n")
    if rollup.raw_analysis:
        md_lines.append("## Full Analysis\n\n")
        md_lines.append(rollup.raw_analysis + "\n\n")
    if rollup.insights:
        md_lines.append("## Insights\n\n")
        for i, ins in enumerate(rollup.insights, 1):
            md_lines.append(
                f"### {i}. [{ins.category.value}] {ins.title} "
                f"(conf {ins.confidence:.0%})\n\n{ins.description}\n\n"
            )
    md_path = date_dir / "nightshift-brief.md"
    md_tmp = md_path.with_suffix(".md.tmp")
    md_tmp.write_text("".join(md_lines), encoding="utf-8")
    md_tmp.replace(md_path)
    log.info("[%s] wrote %s", date_str, md_path)

    stats["status"] = "written"
    stats["insights"] = len(rollup.insights)
    stats["cost_usd"] = EST_COST_PER_DATE_USD
    return stats


async def _main() -> int:
    log.info("=" * 72)
    log.info(
        "W11-3 retro-seed — targets: %s",
        ", ".join(TARGET_DATES),
    )
    log.info("=" * 72)

    results: list[dict] = []
    for date_str in TARGET_DATES:
        try:
            stats = await _seed_one_date(date_str)
        except Exception as e:
            log.error("[%s] fatal: %s", date_str, e, exc_info=True)
            stats = {
                "date": date_str,
                "status": "error",
                "per_video_reports": 0,
                "insights": 0,
                "cost_usd": 0.0,
                "brief_path": "",
            }
        results.append(stats)

    # ── Final summary ────────────────────────────────────────────────────
    total_cost = sum(r["cost_usd"] for r in results)
    print("\n" + "=" * 72)
    print("W11-3 RETRO-SEED SUMMARY")
    print("=" * 72)
    for r in results:
        print(
            f"  {r['date']}  status={r['status']:<22}  "
            f"per_video={r['per_video_reports']:>3}  "
            f"insights={r['insights']:>3}  "
            f"cost=${r['cost_usd']:.2f}"
        )
    print("-" * 72)
    print(f"  TOTAL est. cost: ${total_cost:.2f}")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
