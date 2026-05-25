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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .shared.models import CouncilReport


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
# Brain API auth token — falls back to STRIKE_AUTH_TOKEN (the canonical name
# used everywhere else in NCL). Setting either env var works; STRIKE_AUTH_TOKEN
# is preferred so there's one source of truth for Brain auth.
BRAIN_AUTH_TOKEN = os.getenv("BRAIN_AUTH_TOKEN") or os.getenv("STRIKE_AUTH_TOKEN", "")
if not BRAIN_AUTH_TOKEN:
    log.warning(
        "[council-runner] Neither BRAIN_AUTH_TOKEN nor STRIKE_AUTH_TOKEN set — Brain API calls will fail. Set in .env"  # noqa: E501
    )


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
    from .shared.vector_store_singleton import get_council_vector_store

    source = report.council_type.value  # "youtube" or "x"
    session_id = report.session_id

    # ── 1. ChromaDB Vector Store Indexing ──────────────────────────────
    #
    # Pre-fix (2026-05-24 incident, pid 27623): this function instantiated
    # a fresh CouncilVectorStore per report, which means a fresh
    # chromadb.PersistentClient per video. Run 33 videos through the
    # hourly YTC dedicated loop and you get 33 concurrent clients mmapping
    # the same persistent store; ChromaDB Rust HNSW deadlocks under that
    # access pattern (every CPU sample stuck in chromadb_rust_bindings).
    # Plus each insight was a separate sync upsert call blocking the event
    # loop. Fix:
    #   - shared singleton (`get_council_vector_store`)
    #   - batched upsert via `index_documents_batch`
    #   - sync ChromaDB ops wrapped in `asyncio.to_thread` in vector_store.py
    try:
        data_dir = NCL_BASE / "data"
        vector_store = await get_council_vector_store(data_dir)
        backend = vector_store._backend

        # Build the parallel arrays for a single batched upsert: each
        # insight is one document, plus optionally the report summary.
        # Mirrors the per-document doc_id / metadata shape that
        # `index_insight` and `index_report_summary` would have produced.
        now_iso = datetime.now(timezone.utc).isoformat()
        batch: list[tuple[str, str, dict]] = []
        for insight in report.insights:
            title = insight.title or ""
            desc = insight.description or ""
            tags = list(insight.tags or [])
            doc_id = f"insight-{source}-{session_id}-{title[:30].replace(' ', '_')}"
            text = f"{title}. {desc}"
            if tags:
                text += " " + " ".join(tags)
            batch.append(
                (
                    doc_id,
                    text,
                    {
                        "type": "insight",
                        "source": source,
                        "session_id": session_id,
                        "category": insight.category.value,
                        "confidence": float(insight.confidence or 0.0),
                        "tags": tags,
                        "indexed_at": now_iso,
                    },
                )
            )
        if report.summary:
            batch.append(
                (
                    f"report-{source}-{session_id}",
                    report.summary,
                    {
                        "type": "report_summary",
                        "source": source,
                        "session_id": session_id,
                        "insight_count": len(report.insights),
                        "indexed_at": now_iso,
                    },
                )
            )

        indexed_count = await vector_store.index_documents_batch(batch)
        # Report summary is the trailing element when present.
        insight_indexed = max(0, indexed_count - (1 if report.summary else 0))
        if report.summary:
            log.info("[AUTO-INGEST] Report summary indexed into vector store")

        stats = vector_store.get_stats()
        log.info(
            f"[AUTO-INGEST] Vector store: {insight_indexed}/{len(report.insights)} insights indexed "
            f"({stats.get('documents', '?')} total docs in {backend})"
        )
    except Exception as e:
        log.error(f"[AUTO-INGEST] Vector store indexing failed: {e}", exc_info=True)

    # ── 2. Long-Term Memory Store (async_writer fire-and-forget) ───────
    # Previously this issued a sync httpx POST to /memory/store per report
    # plus one per high-confidence insight — typical 5-video YTC run was
    # 11 sequential HTTP roundtrips at ~200ms each (~2.2s of blocking on
    # the YTC loop). Replaced with async_writer.enqueue() which returns
    # immediately. Falls back to direct create_unit() via memory_store
    # when the async writer isn't initialized, then silently skips if
    # neither path is reachable (JSONL on disk is the source of truth).
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
        f"Key Insights ({len(report.insights)} total):\n" + "\n".join(insight_summaries)
    )

    all_tags = {"council_report", f"council_{source}", "auto_ingested"}
    for ins in report.insights:
        all_tags.update(ins.tags[:5])

    rollup_source = f"council:{source}:{session_id}"
    rollup_meta = {
        "session_id": session_id,
        "report_type": "rollup" if getattr(report, "sources_processed", 1) > 1 else "per_video",
        "insight_count": len(report.insights),
    }
    # Per-video reports carry the video id in the session_id suffix
    if "-" in session_id:
        try:
            parent, _, vid_id = session_id.rpartition("-")
            if parent and vid_id and len(vid_id) < 30:
                rollup_meta["video_id"] = vid_id
                rollup_meta["report_type"] = "per_video"
                rollup_meta["parent_session_id"] = parent
        except Exception:
            pass

    try:
        from ..memory.async_writer import WriteRequest, get_async_writer

        try:
            writer = get_async_writer()
        except RuntimeError:
            writer = None

        if writer is not None:
            await writer.enqueue(
                WriteRequest(
                    content=memory_content[:2000],
                    source=rollup_source,
                    memory_type="semantic",  # council output = synthesized analysis
                    importance=85.0,
                    tags=list(all_tags)[:20],
                    metadata=rollup_meta,
                )
            )
            log.info(
                f"[AUTO-INGEST] Report enqueued to async memory writer " f"(source={rollup_source})"
            )
        else:
            # Fallback: direct create_unit via the brain's in-process memory_store
            # (best-effort; if brain isn't in-process, fall through to skip).
            brain_obj = None
            try:
                from ..api.routes import _brain as brain_obj  # type: ignore
            except Exception:
                brain_obj = None
            if brain_obj is not None and getattr(brain_obj, "memory_store", None):
                try:
                    await brain_obj.memory_store.create_unit(
                        content=memory_content[:2000],
                        source=rollup_source,
                        importance=85.0,
                        tags=list(all_tags)[:20],
                        memory_type="semantic",
                    )
                    log.info("[AUTO-INGEST] Report stored via direct create_unit fallback")
                except Exception as e:
                    log.warning(f"[AUTO-INGEST] Direct create_unit fallback failed: {e}")
            else:
                log.debug(
                    "[AUTO-INGEST] No async writer or in-process brain — JSONL on disk is canonical"
                )
    except Exception as e:
        log.warning(f"[AUTO-INGEST] async memory enqueue failed (non-fatal): {e}")

    # ── 3. Store individual high-confidence insights in memory ─────────
    try:
        high_insights = [i for i in report.insights if i.confidence >= 0.7]
        if high_insights:
            from ..memory.async_writer import WriteRequest, get_async_writer

            try:
                writer = get_async_writer()
            except RuntimeError:
                writer = None

            stored = 0
            for ins in high_insights[:10]:
                payload_tags = list(ins.tags[:10]) + [
                    "council_insight",
                    f"council_{source}",
                    "auto_ingested",
                ]
                ins_source = f"council:{source}:insight"
                ins_meta = {
                    "session_id": session_id,
                    "insight_title": ins.title,
                    "category": ins.category.value,
                    "confidence": ins.confidence,
                }
                if writer is not None:
                    try:
                        await writer.enqueue(
                            WriteRequest(
                                content=f"[{ins.category.value}] {ins.title}: {ins.description[:500]}",  # noqa: E501
                                source=ins_source,
                                memory_type="semantic",
                                importance=ins.confidence * 100,
                                tags=payload_tags[:20],
                                metadata=ins_meta,
                            )
                        )
                        stored += 1
                    except Exception as e:
                        log.debug(f"[AUTO-INGEST] insight enqueue failed: {e}")
            if stored:
                log.info(
                    f"[AUTO-INGEST] {stored}/{len(high_insights)} high-confidence insights "
                    f"enqueued to async memory writer"
                )
    except Exception as e:
        log.warning(f"[AUTO-INGEST] Individual insight enqueue failed: {e}")


def _load_previously_analyzed_video_ids(days: int | None = None) -> set[str]:
    """Load video IDs from recent YTC report JSONs to avoid re-analyzing them.

    Scans council-reports/ for YouTube council JSON files from the last N days.
    Only videos analyzed within the `days` window are skipped — older entries
    are allowed to be re-analyzed.

    Default dedup window reduced from 7d -> 1d (2026-05-21). With a small channel
    list (14 channels) the 7d window exhausted candidates within a day and YTC
    runs produced "no report" every hour for ~10 hours. Override via the
    NCL_YTC_DEDUP_DAYS env var.
    """
    import os

    if days is None:
        try:
            days = int(os.getenv("NCL_YTC_DEDUP_DAYS", "1"))
        except (TypeError, ValueError):
            days = 1
    from .shared.report_writer import REPORTS_DIR

    seen: set[str] = set()
    if not REPORTS_DIR.exists():
        return seen
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        for f in sorted(REPORTS_DIR.glob("youtube-council-*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                # Check report timestamp against the days cutoff
                report_ts = data.get("timestamp", "")
                if report_ts:
                    try:
                        report_dt = datetime.fromisoformat(report_ts.replace("Z", "+00:00"))
                        if report_dt < cutoff:
                            # This report (and all older ones) are outside the window
                            break
                    except (ValueError, TypeError):
                        pass
                else:
                    # No timestamp — try to infer from filename (youtube-council-YYYYMMDD-HHMMSS)
                    try:
                        name_parts = f.stem.split("-")
                        # Expected: youtube-council-YYYYMMDD-HHMMSS-...
                        if len(name_parts) >= 4:
                            date_str = name_parts[2]
                            file_dt = datetime.strptime(date_str, "%Y%m%d").replace(
                                tzinfo=timezone.utc
                            )
                            if file_dt < cutoff:
                                break
                    except (ValueError, IndexError):
                        pass

                for vid in data.get("videos", []):
                    vid_id = vid.get("video_id", "")
                    if vid_id:
                        seen.add(vid_id)
            except Exception:
                continue
    except Exception as e:
        log.warning(f"Could not load previous video IDs for dedup: {e}")
    if seen:
        log.info(f"Dedup: loaded {len(seen)} previously analyzed video IDs (last {days} days)")
    return seen


async def _build_pack_runtime():
    """Build the runtime objects ``run_council_with_pack`` needs.

    Returns a 5-tuple ``(council_engine, fused_retriever, working_context,
    learner, async_writer)`` — any element may be ``None`` if the runtime
    isn't reachable (CLI invocation, brain not yet started, etc.). Callers
    treat ``council_engine is None`` as "pack path unavailable, fall through
    to legacy".

    The brain owns ``memory_store``, ``council_engine``, and (via the
    scheduler) the working-context window and async writer singleton. When
    this runner is invoked from inside the Brain process (autonomous loop or
    ``/councils/run`` endpoint) those references are all live. When invoked
    standalone via ``python3 -m runtime.councils.runner``, none of them are
    — and the pack path will gracefully fall back to the legacy code.
    """
    try:
        from ..api.routes import brain as _brain  # type: ignore
    except Exception:
        _brain = None
    if _brain is None or getattr(_brain, "council_engine", None) is None:
        return None, None, None, None, None

    council_engine = _brain.council_engine
    store = _brain.memory_store

    try:
        from ..memory.retrieval import BM25Index, FusedRetriever

        if not getattr(store, "_bm25_index", None):
            store._bm25_index = BM25Index(store)
        fused = FusedRetriever(
            store,
            store._bm25_index,
            knowledge_graph=getattr(store, "_knowledge_graph", None),
        )
    except Exception as e:
        log.debug("[COUNCILS:PACK] FusedRetriever build failed: %s", e)
        fused = None

    async_writer = None
    try:
        from ..memory.async_writer import get_async_writer

        async_writer = get_async_writer()
    except Exception:
        async_writer = None

    learner = None
    try:
        from ..feedback.source_authority_learner import get_learner

        learner = get_learner()
    except Exception:
        learner = None

    working_context = getattr(_brain, "_working_context_ref", None)
    return council_engine, fused, working_context, learner, async_writer


async def _run_youtube_rollup_with_pack_or_fallback(
    *,
    per_video_reports,
    session_id: str,
):
    """Pack-augmented YouTube rollup synthesis with full fallback.

    The legacy ``synthesize_rollup(per_video_reports, session_id)`` is a
    single-Sonnet call. We wrap it with a council_pack chair pass that
    runs the full universal pack (MMR diversity, temporal split,
    contradiction surfacing, calibration, anonymized peer review, 3-tier
    write-back). The resulting ``CouncilReport`` carries the merged
    insights / videos / duration from the per-video reports (unchanged),
    plus a chair-synthesized summary + raw_analysis from the pack debate.

    On ANY pack-path failure (no brain in-process, retriever crash, council
    engine error, etc.) we fall through to the original ``synthesize_rollup``
    so the YouTube council pipeline NEVER regresses.
    """
    from .shared.models import CouncilReport, CouncilSource
    from .youtube.analyzer import synthesize_rollup

    if not per_video_reports:
        # Mirror synthesize_rollup's empty-case behavior.
        return await synthesize_rollup(per_video_reports, session_id)

    council_engine, fused, working_context, learner, async_writer = await _build_pack_runtime()
    if council_engine is None or fused is None:
        log.info("[YTC:PACK] runtime unavailable — falling back to legacy synthesize_rollup")
        return await synthesize_rollup(per_video_reports, session_id)

    # Build pack prompt from the per-video reports (same content the legacy
    # synthesize_rollup builds, kept structurally identical so the chair has
    # equivalent input).
    try:
        all_insights = []
        all_videos = []
        total_duration = 0.0
        prompt_parts: list[str] = []
        for report in per_video_reports:
            all_insights.extend(report.insights)
            all_videos.extend(report.videos)
            total_duration += report.total_duration_hours
            vid_title = report.videos[0].title if report.videos else "Unknown"
            vid_channel = report.videos[0].channel if report.videos else "Unknown"
            insight_titles = [i.title for i in report.insights]
            prompt_parts.append(
                f"## {vid_title} ({vid_channel})\n"
                f"Summary: {report.summary}\n"
                f"Insights: {'; '.join(insight_titles)}\n"
            )
        topic = f"YouTube Council rollup — {len(per_video_reports)} videos, {total_duration:.1f}h"
        base_prompt = (
            f"Synthesize cross-video patterns from {len(per_video_reports)} individually-analyzed "
            f"YouTube videos ({total_duration:.1f} hours total). For each pattern, surface the "
            f"convergence signal across videos. Surface content opportunities.\n\n"
            + "\n".join(prompt_parts)
        )

        from ..council_pack import run_council_with_pack

        pack_result = await run_council_with_pack(
            council_engine=council_engine,
            topic=topic,
            base_prompt=base_prompt,
            fused_retriever=fused,
            working_context=working_context,
            learner=learner,
            async_writer=async_writer,
            session_id=f"ytc-rollup-{session_id}",
            council_type="councils:youtube_rollup",
            peer_review=True,
        )
        session = pack_result["session"]
        rollup_summary = (session.consensus or "")[:1500]
        chair_synthesis = session.synthesis or ""
        # Compose raw_analysis from chair synthesis + surfaced conflicts +
        # peer-review critiques so the on-disk markdown report carries the
        # full pack-augmented context.
        analysis_parts: list[str] = []
        if chair_synthesis:
            analysis_parts.append(f"## Chair Synthesis\n\n{chair_synthesis}")
        conflicts = pack_result["pack"].get("surfaced_conflicts") or []
        if conflicts:
            analysis_parts.append(
                "## Surfaced Conflicts\n\n" + "\n".join(f"- {c}" for c in conflicts[:5])
            )
        prs = pack_result.get("peer_review") or []
        if prs:
            analysis_parts.append(
                f"## Peer Review ({len(prs)} critiques)\n\n"
                + "\n".join(f"- {pr.get('critique', '')[:300]}" for pr in prs[:3])
            )
        raw_analysis = "\n\n".join(analysis_parts) if analysis_parts else (rollup_summary or "")

        rollup = CouncilReport(
            council_type=CouncilSource.YOUTUBE,
            session_id=session_id,
            sources_processed=len(per_video_reports),
            total_duration_hours=total_duration,
            insights=all_insights,
            summary=rollup_summary or f"YouTube rollup ({len(per_video_reports)} videos)",
            raw_analysis=raw_analysis,
            videos=all_videos,
        )
        log.info(
            "[YTC:PACK] rollup complete pack_session=%s pack_items=%d conflicts=%d peer_reviews=%d writeback_gist=%d",  # noqa: E501
            session.session_id,
            pack_result["pack"].get("pack_size_items", 0),
            len(conflicts),
            len(prs),
            len((pack_result.get("writeback") or {}).get("gist") or ""),
        )
        return rollup
    except Exception as pack_err:
        log.warning(
            "[YTC:PACK] pack path failed (%s) — falling back to legacy synthesize_rollup",
            pack_err,
        )
        return await synthesize_rollup(per_video_reports, session_id)


async def _run_x_pack_augmenter(*, report, session_id: str) -> None:
    """Best-effort pack augmenter for the X (Twitter) council.

    The X council's canonical insight extractor is
    ``analyze_posts(sweep_results, session_id)`` and we don't want to
    duplicate that work. This helper runs a SEPARATE pack-augmented chair
    pass over the produced report so we get calibration + peer review +
    3-tier write-back on the synthesized X analysis — strictly additive,
    runs in-process, no impact on the returned ``CouncilReport``.

    Fails silently (caller wraps in try/except). The X scanner has been
    402'd for a week; the input may always be empty.
    """
    if not report or not report.insights:
        log.debug("[X-COUNCIL:PACK] no insights to augment, skipping pack pass")
        return

    council_engine, fused, working_context, learner, async_writer = await _build_pack_runtime()
    if council_engine is None or fused is None:
        log.debug("[X-COUNCIL:PACK] runtime unavailable — skipping pack pass")
        return

    insight_lines = []
    for i, ins in enumerate(report.insights[:30], 1):
        insight_lines.append(
            f"{i}. [{ins.category.value}] {ins.title} (conf {ins.confidence:.0%}): "
            f"{ins.description[:200]}"
        )
    topic = f"X Council pack augmentation — {len(report.insights)} insights"
    base_prompt = (
        f"X (Twitter) council produced {len(report.insights)} insights from "
        f"{report.sources_processed} posts. Summary: {report.summary or '(none)'}\n\n"
        f"Insights:\n" + "\n".join(insight_lines)
    )

    try:
        from ..council_pack import run_council_with_pack

        pack_result = await run_council_with_pack(
            council_engine=council_engine,
            topic=topic,
            base_prompt=base_prompt,
            fused_retriever=fused,
            working_context=working_context,
            learner=learner,
            async_writer=async_writer,
            session_id=f"x-pack-{session_id}",
            council_type="councils:x_augment",
            peer_review=True,
        )
        log.info(
            "[X-COUNCIL:PACK] augmenter complete pack_session=%s peer_reviews=%d writeback_gist=%d",
            pack_result["session"].session_id,
            len(pack_result.get("peer_review") or []),
            len((pack_result.get("writeback") or {}).get("gist") or ""),
        )
    except Exception as pack_err:
        log.warning("[X-COUNCIL:PACK] pack path failed (%s) — augmentation skipped", pack_err)


async def run_youtube_per_video_only(
    session_id: str,
    dry_run: bool = False,
    progress_cb: object | None = None,
) -> "CouncilReport | None":
    """W11-1 hourly variant: scrape -> download -> transcribe -> per-video
    analysis -> write per-video reports. NO rollup synthesis.

    The cross-video rollup is now produced by the nightshift loop
    (``run_youtube_nightshift``) which fires once at 3am local and consumes
    every per-video report from the prior 24h.

    Skip rules (vs ``run_youtube_council``):
      * If no NEW videos remain after dedup, return None (cycle is a no-op).
      * Per-video download failure is logged and skipped (caller already
        tolerates this via ``download_batch`` returning fewer items).
      * Per-video analysis failure is logged and the next video is tried —
        the gather/return-None path is unchanged.

    Returns a synthetic CouncilReport that carries ``_per_video_reports`` so
    the caller can persist them, or None if nothing was produced. The
    returned report itself is NOT a rollup — its ``summary`` is a static
    "per-video only" placeholder and it should NOT be ingested into memory
    as a rollup (the scheduler writes per-video JSONs only).
    """
    from .shared.models import CouncilReport, CouncilSource
    from .shared.report_writer import write_report
    from .youtube.scraper import download_batch, scrape_recent_videos
    from .youtube.transcriber import cleanup_old_audio, transcribe_batch

    def _progress(step: str, **kwargs):
        if progress_cb is not None:
            try:
                progress_cb(step, **kwargs)
            except Exception:
                pass

    log.info("=" * 60)
    log.info("  YOUTUBE COUNCIL (PER-VIDEO ONLY) — Starting session")
    log.info("=" * 60)

    try:
        cleanup_old_audio()
    except Exception as e:
        log.warning(f"Audio cleanup failed (non-fatal): {e}")

    _progress("scraping")
    log.info("Step 1/4: Scraping channel feeds...")
    videos = await asyncio.to_thread(scrape_recent_videos)
    if not videos:
        log.info("[YTC-PV] No recent videos found — skipping cycle")
        return None

    already_seen = _load_previously_analyzed_video_ids()
    if already_seen:
        before = len(videos)
        videos = [v for v in videos if v.get("video_id", v.get("id", "")) not in already_seen]
        skipped = before - len(videos)
        if skipped:
            log.info(f"[YTC-PV] Dedup skipped {skipped}, {len(videos)} remaining")

    # W11-1 rule: skip cycle if no new videos
    if len(videos) < 1:
        log.info("[YTC-PV] No new videos after dedup — skipping cycle (no rollup attempted)")
        return None

    log.info(f"[YTC-PV] Found {len(videos)} new videos to analyze")
    _progress("downloading", videos_found=len(videos))

    if dry_run:
        log.info("[YTC-PV][DRY RUN] Skipping download/transcribe/analyze")
        return None

    log.info("Step 2/4: Downloading audio...")
    downloaded = await asyncio.to_thread(download_batch, videos)
    if not downloaded:
        # W11-1 rule: download-fail tolerance — try next cycle, no rollup
        log.warning("[YTC-PV] No audio downloaded this cycle — will retry next hour")
        return None

    _progress("transcribing", videos_found=len(videos), videos_transcribed=0)
    log.info("Step 3/4: Transcribing audio...")
    transcribed = await asyncio.to_thread(transcribe_batch, downloaded)
    if not transcribed:
        log.warning("[YTC-PV] No transcriptions produced this cycle")
        return None

    total_duration = sum(t.duration_seconds for _, t in transcribed)
    log.info(f"[YTC-PV] Transcribed {len(transcribed)} videos ({total_duration / 3600:.1f}h)")
    _progress("analyzing", videos_found=len(videos), videos_transcribed=len(transcribed))

    from .youtube.analyzer import analyze_single_video

    log.info(f"Step 4/4: Per-video AI analysis on {len(transcribed)} videos...")
    sem = asyncio.Semaphore(3)

    async def _analyze_one(video_info: dict, transcript, idx: int):
        async with sem:
            vid_id = video_info.get("video_id", f"vid{idx}")
            vid_session = f"{session_id}-{vid_id}"
            log.info(
                f"  [YTC-PV] Analyzing [{idx + 1}/{len(transcribed)}]: "
                f"{video_info.get('title', 'Untitled')}"
            )
            _progress(
                "analyzing_video",
                video_index=idx + 1,
                video_total=len(transcribed),
                video_title=video_info.get("title", ""),
            )
            try:
                report = await analyze_single_video(video_info, transcript, vid_session)
                vid_md, vid_json = write_report(report)
                log.info(f"  [YTC-PV] Per-video report saved: {vid_md.name}")
                await _auto_ingest_report(report)
                return report
            except Exception as e:
                log.error(
                    f"  [YTC-PV] Analysis failed for '{video_info.get('title', '')}': {e}",
                    exc_info=True,
                )
                # W11-1 rule: try next video instead of bailing
                return None

    tasks = [
        _analyze_one(video_info, transcript, i)
        for i, (video_info, transcript) in enumerate(transcribed)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    per_video_reports: list[CouncilReport] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("[YTC-PV][GATHER] per-video task failed: %s", r)
            continue
        if r is not None:
            per_video_reports.append(r)

    if not per_video_reports:
        log.warning("[YTC-PV] All per-video analyses failed this cycle")
        return None

    log.info(
        f"[YTC-PV] Per-video complete: {len(per_video_reports)}/{len(transcribed)} succeeded"
    )

    # Synthetic carrier — NOT a rollup. Caller uses ``_per_video_reports``
    # only; the synthesized rollup is now the nightshift loop's job.
    carrier = CouncilReport(
        council_type=CouncilSource.YOUTUBE,
        session_id=session_id,
        sources_processed=len(per_video_reports),
        total_duration_hours=total_duration,
        insights=[],
        summary="Per-video YTC cycle — rollup deferred to nightshift loop.",
        videos=[],
    )
    carrier._per_video_reports = per_video_reports  # type: ignore[attr-defined]
    return carrier


def _ytc_dict_to_report(data: dict) -> "CouncilReport | None":
    """Best-effort reverse of ``CouncilReport.to_dict()`` for nightshift load.

    Reconstructs just enough of the dataclass tree for ``synthesize_rollup``
    to read ``report.insights[*].title``, ``report.videos[0].title``,
    ``report.videos[0].channel``, ``report.summary`` and
    ``report.total_duration_hours``. Anything missing is filled with safe
    defaults.
    """
    from .shared.models import (
        CouncilReport,
        CouncilSource,
        Insight,
        SignalCategory,
        VideoMeta,
    )

    try:
        ctype = data.get("council_type") or CouncilSource.YOUTUBE.value
        if isinstance(ctype, str):
            try:
                ctype_enum = CouncilSource(ctype)
            except ValueError:
                ctype_enum = CouncilSource.YOUTUBE
        else:
            ctype_enum = CouncilSource.YOUTUBE

        insights_raw = data.get("insights") or []
        insights: list[Insight] = []
        for ins in insights_raw:
            try:
                cat = ins.get("category") or "content"
                try:
                    cat_enum = SignalCategory(cat)
                except ValueError:
                    cat_enum = SignalCategory.CONTENT
                insights.append(
                    Insight(
                        title=ins.get("title", ""),
                        description=ins.get("description", ""),
                        category=cat_enum,
                        confidence=float(ins.get("confidence", 0.5) or 0.5),
                        tags=list(ins.get("tags") or []),
                        source_refs=list(ins.get("source_refs") or []),
                        actionable=bool(ins.get("actionable", False)),
                        action_suggestion=ins.get("action_suggestion", ""),
                    )
                )
            except Exception:
                continue

        videos_raw = data.get("videos") or []
        videos: list[VideoMeta] = []
        for v in videos_raw:
            try:
                videos.append(
                    VideoMeta(
                        video_id=v.get("video_id", ""),
                        title=v.get("title", ""),
                        channel=v.get("channel", ""),
                        channel_id=v.get("channel_id", ""),
                        upload_date=v.get("upload_date", ""),
                        duration_seconds=int(v.get("duration_seconds", 0) or 0),
                        url=v.get("url", ""),
                        description=v.get("description", "") or "",
                        view_count=int(v.get("view_count", 0) or 0),
                        like_count=int(v.get("like_count", 0) or 0),
                        tags=list(v.get("tags") or []),
                        thumbnail_url=v.get("thumbnail_url", "") or "",
                    )
                )
            except Exception:
                continue

        return CouncilReport(
            council_type=ctype_enum,
            session_id=data.get("session_id", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            period_hours=int(data.get("period_hours", 24) or 24),
            sources_processed=int(data.get("sources_processed", 0) or 0),
            total_duration_hours=float(data.get("total_duration_hours", 0.0) or 0.0),
            insights=insights,
            summary=data.get("summary", "") or "",
            raw_analysis=data.get("raw_analysis", "") or "",
            videos=videos,
            posts=[],
        )
    except Exception as e:
        log.warning("[YTC-NIGHTSHIFT] failed to rehydrate report dict: %s", e)
        return None


async def run_youtube_nightshift(
    date_str: str,
    session_id: str | None = None,
) -> "CouncilReport | None":
    """W11-1 nightshift rollup synthesizer.

    Reads every per-video report from
    ``intelligence-scan/council-reports/youtube/<date_str>/`` (where
    ``date_str`` is the local YYYY-MM-DD of the day to roll up — typically
    ``yesterday``), rehydrates them into ``CouncilReport`` objects, and
    runs ``synthesize_rollup(reports, session_id)`` ONLY. No scrape, no
    download, no transcription.

    Requires >= 2 per-video reports to bother synthesizing — a single
    report doesn't have cross-video patterns to surface.

    Returns the synthesized rollup ``CouncilReport`` (the caller writes
    it to ``<date_dir>/nightshift-brief.{json,md}``), or None.
    """
    from .shared.report_writer import REPORTS_DIR
    from .youtube.analyzer import synthesize_rollup

    if session_id is None:
        session_id = (
            f"ytc-nightshift-{date_str}-"
            f"{datetime.now(timezone.utc).strftime('%H%M%S')}"
        )

    date_dir = REPORTS_DIR / "youtube" / date_str
    if not date_dir.exists():
        log.info(
            "[YTC-NIGHTSHIFT] No per-video reports directory for %s (%s) — nothing to roll up",
            date_str,
            date_dir,
        )
        return None

    per_video_reports: list[CouncilReport] = []
    try:
        for f in sorted(date_dir.glob("*.json")):
            # Skip our own output if a prior nightshift wrote here
            if f.name.startswith("nightshift-brief"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("[YTC-NIGHTSHIFT] could not read %s: %s", f.name, e)
                continue
            # Only consider per_video reports (skip stray rollups if any)
            if data.get("report_type") and data.get("report_type") != "per_video":
                continue
            report = _ytc_dict_to_report(data)
            if report is not None:
                per_video_reports.append(report)
    except Exception as e:
        log.error("[YTC-NIGHTSHIFT] glob+load failed for %s: %s", date_dir, e, exc_info=True)
        return None

    if len(per_video_reports) < 2:
        log.info(
            "[YTC-NIGHTSHIFT] only %d per-video report(s) for %s — skipping rollup synthesis",
            len(per_video_reports),
            date_str,
        )
        return None

    log.info(
        "[YTC-NIGHTSHIFT] synthesizing rollup from %d per-video reports (%s)",
        len(per_video_reports),
        date_str,
    )
    rollup = await synthesize_rollup(per_video_reports, session_id)
    log.info(
        "[YTC-NIGHTSHIFT] rollup complete: %d insights, %.1fh total",
        len(rollup.insights),
        rollup.total_duration_hours,
    )
    return rollup


async def run_youtube_council(
    session_id: str,
    dry_run: bool = False,
    progress_cb: object | None = None,
) -> CouncilReport | None:
    """Run the full YouTube Council pipeline. Returns report for War Room.

    Args:
        progress_cb: Optional callable(step: str, **kwargs) to report progress.
                     Called with step name and optional videos_found, videos_transcribed, etc.
    """
    from .shared.report_writer import write_report
    from .youtube.scraper import download_batch, scrape_recent_videos
    from .youtube.transcriber import cleanup_old_audio, transcribe_batch

    def _progress(step: str, **kwargs):
        if progress_cb is not None:
            try:
                progress_cb(step, **kwargs)
            except Exception:
                pass

    log.info("=" * 60)
    log.info("  YOUTUBE COUNCIL — Starting session")
    log.info("=" * 60)

    # Cleanup old audio files to prevent unbounded disk growth
    try:
        cleanup_old_audio()
    except Exception as e:
        log.warning(f"Audio cleanup failed (non-fatal): {e}")

    # Step 1: Scrape channel metadata (with Strike Point scoring)
    _progress("scraping")
    log.info("Step 1/4: Scraping channel feeds (Strike Point targeting)...")
    videos = await asyncio.to_thread(scrape_recent_videos)
    if not videos:
        log.warning("No recent videos found — YouTube Council has nothing to process")
        return None

    # Dedup: skip videos already analyzed in previous runs
    already_seen = _load_previously_analyzed_video_ids()
    if already_seen:
        before = len(videos)
        videos = [v for v in videos if v.get("video_id", v.get("id", "")) not in already_seen]
        skipped = before - len(videos)
        if skipped:
            log.info(
                f"Dedup: skipped {skipped} previously analyzed videos, {len(videos)} remaining"
            )
        if not videos:
            log.info("All recent videos already analyzed — nothing new to process")
            return None

    log.info(f"Found {len(videos)} new videos to analyze")
    _progress("downloading", videos_found=len(videos))

    if dry_run:
        log.info("[DRY RUN] Skipping download, transcription, and analysis")
        for v in videos:
            score = v.get("strike_score", 0)
            log.info(
                f"  - {v['title']} ({v.get('duration', 0) // 60}m) [{v['channel']}] score={score}"
            )
        return None

    # Step 2: Download audio
    log.info("Step 2/4: Downloading audio...")
    downloaded = await asyncio.to_thread(download_batch, videos)
    if not downloaded:
        log.warning("No audio downloaded — YouTube Council cannot proceed")
        return None

    # Step 3: Transcribe
    _progress("transcribing", videos_found=len(videos), videos_transcribed=0)
    log.info("Step 3/4: Transcribing audio...")
    transcribed = await asyncio.to_thread(transcribe_batch, downloaded)
    if not transcribed:
        log.warning("No transcriptions produced — YouTube Council cannot proceed")
        return None

    total_duration = sum(t.duration_seconds for _, t in transcribed)
    log.info(f"Transcribed {len(transcribed)} videos ({total_duration / 3600:.1f}h)")
    _progress("analyzing", videos_found=len(videos), videos_transcribed=len(transcribed))

    # Step 4: Per-video AI analysis (one report per video)
    from .youtube.analyzer import analyze_single_video

    log.info(f"Step 4/5: Running per-video AI analysis on {len(transcribed)} videos...")
    per_video_reports: list[CouncilReport] = []

    # Concurrency-limited per-video analysis (max 3 concurrent API calls)
    sem = asyncio.Semaphore(3)

    async def _analyze_one(video_info: dict, transcript, idx: int):
        async with sem:
            vid_id = video_info.get("video_id", f"vid{idx}")
            vid_session = f"{session_id}-{vid_id}"
            log.info(
                f"  Analyzing [{idx + 1}/{len(transcribed)}]: {video_info.get('title', 'Untitled')}"
            )
            _progress(
                "analyzing_video",
                video_index=idx + 1,
                video_total=len(transcribed),
                video_title=video_info.get("title", ""),
            )
            try:
                report = await analyze_single_video(video_info, transcript, vid_session)
                # Save individual report
                vid_md, vid_json = write_report(report)
                log.info(f"  Per-video report saved: {vid_md.name}")
                # Ingest individual report into memory
                await _auto_ingest_report(report)
                return report
            except Exception as e:
                log.error(
                    f"  Analysis failed for '{video_info.get('title', '')}': {e}", exc_info=True
                )
                return None

    tasks = [
        _analyze_one(video_info, transcript, i)
        for i, (video_info, transcript) in enumerate(transcribed)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    per_video_reports = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("[GATHER] ytc_per_video_analyze task failed: %s", r)
            continue
        if r is not None:
            per_video_reports.append(r)

    if not per_video_reports:
        log.warning("All per-video analyses failed — no reports generated")
        return None

    log.info(f"Per-video analysis complete: {len(per_video_reports)}/{len(transcribed)} succeeded")

    # Step 5: Cross-video rollup synthesis (Wave 3: routed through council_pack
    # for calibration + peer review + 3-tier write-back, with full fallback to
    # the legacy ``synthesize_rollup`` on ANY failure).
    log.info("Step 5/5: Synthesizing cross-video rollup...")
    _progress("synthesizing_rollup")
    rollup = await _run_youtube_rollup_with_pack_or_fallback(
        per_video_reports=per_video_reports,
        session_id=session_id,
    )

    # Save rollup as the main session report
    md_path, json_path = write_report(rollup)
    log.info("YouTube Council rollup saved:")
    log.info(f"  Markdown: {md_path}")
    log.info(f"  JSON: {json_path}")
    log.info(f"  Total insights: {len(rollup.insights)}")
    log.info(f"  Videos processed: {rollup.sources_processed}")
    log.info(f"  Total duration: {rollup.total_duration_hours:.1f}h")
    log.info(f"  Per-video reports: {len(per_video_reports)}")

    # Auto-ingest rollup
    await _auto_ingest_report(rollup)

    # Attach per-video reports to rollup for callers that need them
    rollup._per_video_reports = per_video_reports  # type: ignore[attr-defined]

    return rollup


async def run_x_council(
    session_id: str,
    dry_run: bool = False,
) -> CouncilReport | None:
    """Run the full X (Twitter) Council pipeline. Returns report for War Room."""
    from .shared.report_writer import write_report
    from .xai.analyzer import analyze_posts
    from .xai.scanner import full_sweep

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

    # Wave 3: best-effort pack-augmented chair pass on the same posts. This
    # adds calibration + peer review + 3-tier write-back on the synthesized
    # X analysis. The existing ``report`` is the canonical insight extractor
    # and is what we save to disk; pack augmentation is purely additive.
    try:
        await _run_x_pack_augmenter(report=report, session_id=session_id)
    except Exception as pack_err:
        log.warning(
            "[X-COUNCIL:PACK] pack augmenter failed (%s) — continuing with legacy report", pack_err
        )

    # Save report
    md_path, json_path = write_report(report)
    log.info("X Council report saved:")
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
        log.info(
            "[snapshot] No latest_brief.json on disk — councils will spawn without prior brief"
        )
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
    group.add_argument(
        "--both", action="store_true", default=True, help="Run both councils (default)"
    )
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
