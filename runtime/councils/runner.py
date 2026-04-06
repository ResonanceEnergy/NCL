"""
NARTIX Council Runner — Orchestrates YouTube and X intelligence councils.

Runs both councils in parallel, collects reports, and saves them to
NCL/intelligence-scan/ for the Awarebot-FPC pipeline.

Usage:
    python3 -m runtime.councils.runner --both        # Run both councils (default)
    python3 -m runtime.councils.runner --youtube      # YouTube council only
    python3 -m runtime.councils.runner --x            # X council only
    python3 -m runtime.councils.runner --both --dry   # Dry run (scrape only, no AI analysis)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Setup logging before imports
NCL_BASE = Path.home() / "Projects" / "NCL"
LOG_DIR = NCL_BASE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "council-runner.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
        ),
    ],
)
log = logging.getLogger("ncl.councils.runner")


async def run_youtube_council(
    session_id: str,
    dry_run: bool = False,
) -> None:
    """Run the full YouTube Council pipeline."""
    from .youtube.scraper import scrape_recent_videos, download_batch
    from .youtube.transcriber import transcribe_batch
    from .youtube.analyzer import analyze_videos
    from .shared.report_writer import write_report

    log.info("=" * 60)
    log.info("  YOUTUBE COUNCIL — Starting session")
    log.info("=" * 60)

    # Step 1: Scrape channel metadata
    log.info("Step 1/4: Scraping channel feeds...")
    videos = scrape_recent_videos()
    if not videos:
        log.warning("No recent videos found — YouTube Council has nothing to process")
        return

    log.info(f"Found {len(videos)} videos in the last 24 hours")

    if dry_run:
        log.info("[DRY RUN] Skipping download, transcription, and analysis")
        for v in videos:
            log.info(f"  - {v['title']} ({v.get('duration', 0) // 60}m) [{v['channel']}]")
        return

    # Step 2: Download audio
    log.info("Step 2/4: Downloading audio...")
    downloaded = download_batch(videos)
    if not downloaded:
        log.warning("No audio downloaded — YouTube Council cannot proceed")
        return

    # Step 3: Transcribe
    log.info("Step 3/4: Transcribing audio...")
    transcribed = transcribe_batch(downloaded)
    if not transcribed:
        log.warning("No transcriptions produced — YouTube Council cannot proceed")
        return

    total_duration = sum(t.duration_seconds for _, t in transcribed)
    log.info(f"Transcribed {len(transcribed)} videos ({total_duration / 3600:.1f}h)")

    # Step 4: Analyze with AI council
    log.info("Step 4/4: Running AI analysis...")
    report = await analyze_videos(transcribed, session_id)

    # Save report
    md_path, json_path = write_report(report)
    log.info(f"YouTube Council report saved:")
    log.info(f"  Markdown: {md_path}")
    log.info(f"  JSON: {json_path}")
    log.info(f"  Insights: {len(report.insights)}")
    log.info(f"  Videos processed: {report.sources_processed}")
    log.info(f"  Total duration: {report.total_duration_hours:.1f}h")


async def run_x_council(
    session_id: str,
    dry_run: bool = False,
) -> None:
    """Run the full X (Twitter) Council pipeline."""
    from .xai.scanner import full_sweep
    from .xai.analyzer import analyze_posts
    from .shared.report_writer import write_report

    log.info("=" * 60)
    log.info("  X (TWITTER) COUNCIL — Starting session")
    log.info("=" * 60)

    # Step 1: Full intelligence sweep
    log.info("Step 1/2: Running full intelligence sweep...")
    sweep_results = await full_sweep()

    total_posts = sum(len(v) for v in sweep_results.values())
    if total_posts == 0:
        log.warning("No posts collected — X Council has nothing to process")
        return

    log.info(
        f"Sweep complete: {total_posts} posts "
        f"({len(sweep_results.get('accounts', []))} from accounts, "
        f"{len(sweep_results.get('keywords', []))} from keywords, "
        f"{len(sweep_results.get('trending', []))} from trending)"
    )

    if dry_run:
        log.info("[DRY RUN] Skipping AI analysis")
        return

    # Step 2: Analyze with AI council
    log.info("Step 2/2: Running AI analysis...")
    report = await analyze_posts(sweep_results, session_id)

    # Save report
    md_path, json_path = write_report(report)
    log.info(f"X Council report saved:")
    log.info(f"  Markdown: {md_path}")
    log.info(f"  JSON: {json_path}")
    log.info(f"  Insights: {len(report.insights)}")
    log.info(f"  Posts analyzed: {report.sources_processed}")


async def run_both(session_id: str, dry_run: bool = False) -> None:
    """Run YouTube and X councils in parallel."""
    yt_session = f"yt-{session_id}"
    x_session = f"x-{session_id}"

    log.info("Running YouTube and X councils in parallel...")

    results = await asyncio.gather(
        run_youtube_council(yt_session, dry_run),
        run_x_council(x_session, dry_run),
        return_exceptions=True,
    )

    for i, result in enumerate(results):
        council = "YouTube" if i == 0 else "X"
        if isinstance(result, Exception):
            log.error(f"{council} Council failed: {result}")
        else:
            log.info(f"{council} Council completed successfully")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NARTIX Intelligence Council Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m runtime.councils.runner --both        Run both councils
  python3 -m runtime.councils.runner --youtube     YouTube only
  python3 -m runtime.councils.runner --x           X (Twitter) only
  python3 -m runtime.councils.runner --both --dry  Dry run (scrape only)
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--both", action="store_true", default=True, help="Run both councils (default)")
    group.add_argument("--youtube", action="store_true", help="YouTube council only")
    group.add_argument("--x", action="store_true", help="X (Twitter) council only")
    parser.add_argument("--dry", action="store_true", help="Dry run — scrape only, no AI analysis")
    parser.add_argument("--session-id", type=str, default=None, help="Custom session ID")

    args = parser.parse_args()

    session_id = args.session_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log.info(f"Council session: {session_id}")

    if args.youtube:
        asyncio.run(run_youtube_council(session_id, args.dry))
    elif args.x:
        asyncio.run(run_x_council(session_id, args.dry))
    else:
        asyncio.run(run_both(session_id, args.dry))

    log.info("Council session complete.")


if __name__ == "__main__":
    main()
