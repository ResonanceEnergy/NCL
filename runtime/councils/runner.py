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
import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .shared.models import CouncilReport

import aiohttp

# Setup logging before imports
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
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

# Brain API for memory store ingestion (localhost when in-process or CLI)
BRAIN_API = os.getenv("NCL_BRAIN_URL", "http://127.0.0.1:8800")
BRAIN_AUTH_TOKEN = os.getenv("BRAIN_AUTH_TOKEN", "")
if not BRAIN_AUTH_TOKEN:
    log.warning("[council-runner] BRAIN_AUTH_TOKEN not set — Brain API calls will fail. Set in .env")


async def _auto_ingest_report(report: CouncilReport) -> None:
    """
    Auto-ingest a council report into ChromaDB vector store AND long-term memory.

    Called after write_report() so every council run automatically:
    1. Indexes each insight into ChromaDB for RAG retrieval
    2. Indexes the report summary into ChromaDB
    3. Stores the full report in the memory store for short/long-term recall

    This closes the gap where reports were saved to disk but never entered
    the searchable knowledge base.
    """
    from .shared.vector_store import CouncilVectorStore

    source = report.council_type.value  # "youtube" or "x"
    session_id = report.session_id

    # ── 1. ChromaDB Vector Store Indexing ──────────────────────────────
    try:
        data_dir = NCL_BASE / "data"
        vector_store = CouncilVectorStore(data_dir=data_dir)
        backend = await vector_store.init()
        log.info(f"[AUTO-INGEST] Vector store initialized: {backend}")

        # Index each insight
        indexed_count = 0
        for insight in report.insights:
            try:
                await vector_store.index_insight(
                    insight_title=insight.title,
                    insight_description=insight.description,
                    session_id=session_id,
                    source=source,
                    category=insight.category.value,
                    tags=insight.tags,
                    confidence=insight.confidence,
                )
                indexed_count += 1
            except Exception as e:
                log.warning(f"[AUTO-INGEST] Failed to index insight '{insight.title}': {e}")

        # Index report summary
        if report.summary:
            try:
                await vector_store.index_report_summary(
                    session_id=session_id,
                    source=source,
                    summary=report.summary,
                    insight_count=len(report.insights),
                )
                log.info(f"[AUTO-INGEST] Report summary indexed into vector store")
            except Exception as e:
                log.warning(f"[AUTO-INGEST] Failed to index report summary: {e}")

        stats = vector_store.get_stats()
        log.info(
            f"[AUTO-INGEST] Vector store: {indexed_count}/{len(report.insights)} insights indexed "
            f"({stats.get('documents', '?')} total docs in {backend})"
        )
    except Exception as e:
        log.error(f"[AUTO-INGEST] Vector store indexing failed: {e}", exc_info=True)

    # ── 2. Long-Term Memory Store ──────────────────────────────────────
    try:
        # Build a rich memory content block from the report
        insight_summaries = []
        for i, ins in enumerate(report.insights[:10], 1):
            insight_summaries.append(
                f"{i}. [{ins.category.value}] {ins.title} "
                f"(confidence: {ins.confidence:.0%}): {ins.description[:200]}"
            )

        memory_content = (
            f"{'YouTube' if source == 'youtube' else 'X (Twitter)'} Council Report — "
            f"Session {session_id}\n\n"
            f"Executive Summary: {(report.summary or 'No summary')[:500]}\n\n"
            f"Key Insights ({len(report.insights)} total):\n"
            + "\n".join(insight_summaries)
        )

        # Build tags from all insight tags + council metadata
        all_tags = {"council_report", f"council_{source}", "auto_ingested"}
        for ins in report.insights:
            all_tags.update(ins.tags[:5])

        payload = {
            "content": memory_content[:2000],
            "source": f"council:{source}:{session_id}",
            "importance": 85.0,
            "tags": list(all_tags)[:20],
        }

        headers = {"Content-Type": "application/json"}
        if BRAIN_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {BRAIN_AUTH_TOKEN}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BRAIN_API}/memory/store",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201):
                    result = await resp.json()
                    log.info(
                        f"[AUTO-INGEST] Report stored in long-term memory: "
                        f"unit_id={result.get('unit_id', 'unknown')}"
                    )
                else:
                    body = await resp.text()
                    log.warning(
                        f"[AUTO-INGEST] Memory store returned {resp.status}: {body[:200]}"
                    )
    except aiohttp.ClientError as e:
        log.warning(f"[AUTO-INGEST] Memory store unreachable (Brain API down?): {e}")
    except Exception as e:
        log.error(f"[AUTO-INGEST] Memory store ingestion failed: {e}", exc_info=True)

    # ── 3. Store individual high-confidence insights in memory ─────────
    try:
        high_insights = [i for i in report.insights if i.confidence >= 0.7]
        stored = 0
        if high_insights:
            headers = {"Content-Type": "application/json"}
            if BRAIN_AUTH_TOKEN:
                headers["Authorization"] = f"Bearer {BRAIN_AUTH_TOKEN}"

            async with aiohttp.ClientSession() as session:
                for ins in high_insights[:10]:
                    try:
                        payload = {
                            "content": f"[{ins.category.value}] {ins.title}: {ins.description[:500]}",
                            "source": f"council:{source}:insight",
                            "importance": ins.confidence * 100,
                            "tags": list(ins.tags[:10]) + [
                                "council_insight", f"council_{source}", "auto_ingested"
                            ],
                        }
                        async with session.post(
                            f"{BRAIN_API}/memory/store",
                            json=payload,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=5),
                        ) as resp:
                            if resp.status in (200, 201):
                                stored += 1
                    except Exception as e:
                        log.warning(f"[AUTO-INGEST] Failed to store insight '{ins.title[:50]}': {e}")
            log.info(
                f"[AUTO-INGEST] {stored}/{len(high_insights)} high-confidence insights "
                f"stored in memory"
            )
    except Exception as e:
        log.warning(f"[AUTO-INGEST] Individual insight storage failed: {e}")


async def run_youtube_council(
    session_id: str,
    dry_run: bool = False,
) -> CouncilReport | None:
    """Run the full YouTube Council pipeline. Returns report for War Room."""
    from .youtube.scraper import scrape_recent_videos, download_batch
    from .youtube.transcriber import transcribe_batch
    from .youtube.analyzer import analyze_videos
    from .shared.report_writer import write_report

    log.info("=" * 60)
    log.info("  YOUTUBE COUNCIL — Starting session")
    log.info("=" * 60)

    # Step 1: Scrape channel metadata (with Strike Point scoring)
    # scrape_recent_videos() uses time.sleep() for polite rate limiting, so
    # it is run in a thread pool to avoid blocking the event loop.
    log.info("Step 1/4: Scraping channel feeds (Strike Point targeting)...")
    videos = await asyncio.to_thread(scrape_recent_videos)
    if not videos:
        log.warning("No recent videos found — YouTube Council has nothing to process")
        return None

    log.info(f"Found {len(videos)} videos in the last 24 hours")

    if dry_run:
        log.info("[DRY RUN] Skipping download, transcription, and analysis")
        for v in videos:
            score = v.get("strike_score", 0)
            log.info(f"  - {v['title']} ({v.get('duration', 0) // 60}m) [{v['channel']}] score={score}")
        return None

    # Step 2: Download audio
    # download_batch() does blocking yt-dlp I/O; run in thread pool.
    log.info("Step 2/4: Downloading audio...")
    downloaded = await asyncio.to_thread(download_batch, videos)
    if not downloaded:
        log.warning("No audio downloaded — YouTube Council cannot proceed")
        return None

    # Step 3: Transcribe
    # transcribe_batch() does blocking Whisper inference; run in thread pool.
    log.info("Step 3/4: Transcribing audio...")
    transcribed = await asyncio.to_thread(transcribe_batch, downloaded)
    if not transcribed:
        log.warning("No transcriptions produced — YouTube Council cannot proceed")
        return None

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

    # Auto-ingest into ChromaDB vector store + long-term memory
    await _auto_ingest_report(report)

    return report


async def run_x_council(
    session_id: str,
    dry_run: bool = False,
) -> CouncilReport | None:
    """Run the full X (Twitter) Council pipeline. Returns report for War Room."""
    from .xai.scanner import full_sweep
    from .xai.analyzer import analyze_posts
    from .shared.report_writer import write_report

    log.info("=" * 60)
    log.info("  X (TWITTER) COUNCIL — Starting session")
    log.info("=" * 60)

    # Step 1: Full intelligence sweep (X API v2 → twscrape → Grok fallback)
    log.info("Step 1/2: Running full intelligence sweep...")
    sweep_results = await full_sweep()

    total_posts = sum(len(v) for v in sweep_results.values())
    if total_posts == 0:
        log.warning("No posts collected — X Council has nothing to process")
        return None

    log.info(
        f"Sweep complete: {total_posts} posts "
        f"({len(sweep_results.get('accounts', []))} from accounts, "
        f"{len(sweep_results.get('keywords', []))} from keywords, "
        f"{len(sweep_results.get('trending', []))} from trending)"
    )

    if dry_run:
        log.info("[DRY RUN] Skipping AI analysis")
        return None

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

    # Auto-ingest into ChromaDB vector store + long-term memory
    await _auto_ingest_report(report)

    return report


async def _snapshot_intel_state(session_id: str) -> None:
    """Persist a snapshot of the latest intelligence brief at council spawn-time.

    Reads from NCL/data/intelligence/latest_brief.json (canonical location used
    by IntelligenceEngine) and writes a stable copy to
    NCL/intelligence-scan/snapshots/<session_id>.json so War Room synthesis can
    cite what was known at council launch.
    """
    candidate_paths = [
        NCL_BASE / "data" / "intelligence" / "latest_brief.json",
        NCL_BASE / "intelligence-scan" / "latest_brief.json",
    ]
    src = next((p for p in candidate_paths if p.exists()), None)
    if not src:
        log.info("[snapshot] No latest_brief.json on disk — councils will spawn without prior brief")
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"[snapshot] Failed to parse {src}: {e}")
        return
    snapshot_dir = NCL_BASE / "intelligence-scan" / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out = snapshot_dir / f"{session_id}.json"
    payload = {
        "session_id": session_id,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "source": str(src),
        "brief": data,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info(f"[snapshot] Pre-brief snapshot saved → {out.name}")


async def run_both(session_id: str, dry_run: bool = False) -> None:
    """Run YouTube and X councils in parallel, then War Room synthesis."""
    from .shared.models import CouncilReport
    from .shared.war_room_bridge import run_war_room_analysis

    yt_session = f"yt-{session_id}"
    x_session = f"x-{session_id}"

    # Pre-brief snapshot — capture latest IntelBrief so the War Room synthesis
    # can reference what the brain "knew" at council spawn-time. Best-effort:
    # we read the on-disk latest_brief.json directly to avoid coupling to a
    # live engine instance.
    try:
        await _snapshot_intel_state(session_id)
    except Exception as e:
        log.warning(f"Pre-brief snapshot failed (non-fatal): {e}")

    log.info("Running YouTube and X councils in parallel...")

    results = await asyncio.gather(
        run_youtube_council(yt_session, dry_run),
        run_x_council(x_session, dry_run),
        return_exceptions=True,
    )

    yt_report: CouncilReport | None = None
    x_report: CouncilReport | None = None

    for i, result in enumerate(results):
        council = "YouTube" if i == 0 else "X"
        if isinstance(result, Exception):
            log.error(f"{council} Council failed: {result}")
        elif isinstance(result, CouncilReport):
            log.info(f"{council} Council completed — {len(result.insights)} insights")
            if i == 0:
                yt_report = result
            else:
                x_report = result
        else:
            log.info(f"{council} Council completed (no report returned)")

    # ── War Room Synthesis ──────────────────────────────────────────
    if not dry_run and (yt_report or x_report):
        log.info("")
        log.info("=" * 60)
        log.info("  WAR ROOM — Strategic synthesis")
        log.info("=" * 60)

        try:
            briefing_path = await run_war_room_analysis(yt_report, x_report, session_id)
            if briefing_path:
                log.info(f"War Room briefing saved → {briefing_path}")
                log.info("Directives routed to mandate-generation/input/ (pending approval)")
            else:
                log.warning("War Room produced no briefing")
        except Exception as e:
            log.error(f"War Room analysis failed: {e}")
    elif dry_run:
        log.info("[DRY RUN] Skipping War Room synthesis")


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
