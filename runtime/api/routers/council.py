"""Council endpoints (/council/*, /councils/*) extracted from routes.py.

Owns the multi-LLM debate surface that backs the FirstStrike Council /
Strike Point / YTC tabs:

    POST   /council/spawn                       — spawn Delphi-MAD session
    GET    /council/session/{session_id}        — full session detail
    GET    /council/sessions                    — list in-memory sessions
    GET    /council/quality                     — accepted/rejected rollup
    GET    /council/youtube/channels            — list followed YT channels
    POST   /council/youtube/channels            — follow channel
    DELETE /council/youtube/channels            — unfollow channel
    GET    /council/youtube/reports             — list YTC reports
    GET    /council/youtube/reports/{filename}  — fetch YTC report
    POST   /council/youtube/run                 — trigger YTC scrape/analyze
    GET    /council/youtube/status/{session_id} — poll YTC run progress
    POST   /councils/run                        — pack-routed council runner
    GET    /councils/reports                    — list council .md reports
    GET    /councils/reports/{filename}         — fetch council report
    POST   /councils/rag                        — RAG search across knowledge
    GET    /councils/knowledge-base/stats       — KB stats
    GET    /councils/vector-store/stats         — vector store stats
    POST   /councils/vector-store/backfill      — backfill from disk reports
    POST   /councils/multi-agent                — multi-agent orchestrator
    GET    /councils/status                     — store + replay health

`/council-runner/*` endpoints are intentionally NOT extracted here — W5-06
is retiring ``runtime/council_runner/`` and will fold those handlers into
``council_pack`` separately. Leaving them in routes.py prevents an import
race between this wave and that one.

All handlers preserve their original auth posture: every endpoint is
gated by ``verify_strike_token_dep`` (DI factory in :mod:`runtime.api.deps`),
and the three handlers that originally called ``_check_rate_limit``
continue to do so (``/council/spawn``, ``/councils/run``,
``/councils/multi-agent``). ``_check_rate_limit`` is still reached via the
legacy ``from .. import routes as _routes`` shim because it lives on the
``routes`` module and has not yet been promoted to a DI factory — same
posture as the already-migrated ``routers/pump.py``.

Module-level globals (``brain``, ``_council_store``, ``_replay_engine``,
``_autonomous``, ``config``) arrive via ``Depends()`` injection rather
than lazy module reads. The vector-store / knowledge-base singletons +
their init-locks are owned by THIS module (they were already private to
the council endpoints in the monolith).

W10C-5 (2026-05-24): Converted from the legacy ``from .. import routes
as _routes`` lazy-import pattern to FastAPI ``Depends()`` injection.
Mirrors the W8-A8 / W10B-3 / W10C-2..4 conversions of routers/feedback.py,
routers/system.py, routers/journal.py, routers/mandate.py,
routers/memory.py, routers/portfolio.py, routers/intel-equivalent. Two new
DI factories — ``get_council_store`` and ``get_replay_engine`` — were
added to ``runtime.api.deps`` to back the ``/councils/status`` rollup.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..deps import (
    get_autonomous,
    get_brain,
    get_council_store,
    get_replay_engine,
    verify_strike_token_dep,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["council"])


# ── Pydantic bodies ───────────────────────────────────────────────────────


class CouncilSpawnBody(BaseModel):
    topic: str = ""
    prompt: str = ""
    members: list[str] | None = None
    priority: str = "P2"


class CouncilRunRequest(BaseModel):
    """Request body for council runner trigger."""

    council_type: str = Field(..., description="Council type: 'youtube', 'x', or 'both'")
    dry_run: bool = Field(default=False, description="Dry run (scrape only, no AI)")


class YouTubeChannelBody(BaseModel):
    url: str
    name: str = ""


class RAGQueryRequest(BaseModel):
    """RAG query across council knowledge."""

    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    filter_type: str | None = Field(default=None, description="insight, transcript, report_summary")
    filter_source: str | None = Field(default=None, description="youtube or x")


class MultiAgentRequest(BaseModel):
    """Request to run multi-agent council analysis."""

    source_material: str = Field(..., min_length=10, description="Content to analyze")
    pipeline: str = Field(default="youtube", description="youtube or x")


# ── /council/* — Delphi-MAD session endpoints ─────────────────────────────


@router.post("/council/spawn")
async def spawn_council_session(
    request: Request,
    body: CouncilSpawnBody | None = None,
    topic: str = Query(default=""),
    prompt: str = Query(default=""),
    members: str = Query(default=""),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Spawn a new council debate session.

    Accepts topic/prompt/members as query params OR as JSON body.
    JSON body takes precedence when present.

    Returns:
        Dict with session details
    """
    from .. import routes as _routes

    _routes._check_rate_limit(request)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Merge: body fields override query params
    _topic = (body.topic if body and body.topic else topic) or "General council session"
    _prompt = (body.prompt if body and body.prompt else prompt) or _topic
    _members = (
        body.members
        if body and body.members
        else ([m.strip() for m in members.split(",") if m.strip()] if members else None)
    )

    # Pre-generate the session ID so the returned ID matches the one stored by spawn_council_session.  # noqa: E501
    # We pass it through brain → council_engine so council_sessions is keyed on this exact ID.
    session_id = (
        f"council-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"  # noqa: E501
    )

    async def _run_council():
        try:
            # Route through the universal council_pack pipeline (12 fixes:
            # MMR diversity, temporal split, contradiction surfacing,
            # calibration, anonymized peer review, 3-tier write-back, etc.).
            # The helper falls back to the legacy ``spawn_council_session``
            # on any pack-path failure, so this endpoint NEVER regresses.
            session = await brain._run_council_with_pack_or_fallback(
                topic=_topic,
                prompt=_prompt,
                trigger="api:council_spawn",
                members=_members,
                session_id=session_id,
            )
            await brain._log_event(
                "council_spawn_complete",
                f"Council session complete: {session.session_id} — {session.topic}",
                metadata={
                    "session_id": session.session_id,
                    "consensus": session.consensus,
                },
            )
        except Exception as e:
            log.exception(f"[/council/spawn] background council failed: {e}")
            await brain._log_event(
                "council_spawn_error",
                f"Council session failed: {e}",
            )

    task = asyncio.create_task(_run_council())
    task.add_done_callback(
        lambda t: log.error(f"Council spawn task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )  # noqa: E501

    return {
        "session_id": session_id,
        "topic": _topic,
        "status": "queued",
        "consensus": None,
        "recommendations": [],
        "message": "Council session queued — running in background. Poll /council/session/{session_id} for results.",  # noqa: E501
    }


@router.get("/council/session/{session_id}")
async def get_council_session(
    session_id: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Get council session details.

    Args:
        session_id: Council session ID

    Returns:
        Session details
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    session = brain.council_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session.session_id,
        "topic": session.topic,
        "status": session.status.value,
        "responses": session.responses,
        "rounds": [
            {
                "round_number": r.round_number,
                "round_type": r.round_type,
                "responses": r.responses,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in session.rounds
        ],
        "synthesis": session.synthesis,
        "consensus": session.consensus,
        "dissents": session.dissents,
        "recommendations": session.recommendations,
        "created_at": session.created_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


@router.get("/council/sessions")
async def list_council_sessions(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List all in-memory Delphi-MAD council sessions."""
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    sessions = []
    for sid, session in brain.council_sessions.items():
        sessions.append(
            {
                "session_id": session.session_id,
                "topic": session.topic,
                "status": session.status.value,
                "consensus": session.consensus or "",
                "member_count": len(session.members),
                "round_count": len(session.rounds),
                "created_at": session.created_at.isoformat(),
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            }
        )
    # Sort newest first
    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/council/quality")
async def council_quality(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Per-status counter (complete/failed/synthesizing) since Brain start.

    Quality metric for the council pipeline: accepted (complete with consensus)
    vs rejected (failed / quorum_failure / synthesis_error). Lets us monitor
    whether councils are producing good-enough output to act on.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    counts = dict(getattr(brain, "_council_quality", {}))
    # Also rollup current on-disk state
    on_disk = {"complete": 0, "failed": 0, "debating": 0, "synthesizing": 0}
    for sess in brain.council_sessions.values():
        on_disk[sess.status.value] = on_disk.get(sess.status.value, 0) + 1
    total = sum(on_disk.values()) or 1
    accepted = on_disk.get("complete", 0)
    return {
        "since_start": counts,
        "current_state": on_disk,
        "accepted_count": accepted,
        "rejected_count": total - accepted,
        "accepted_pct": round(100.0 * accepted / total, 1),
    }


# ── /council/youtube/* — Channel subscription + YTC reports ───────────────
# Channel subscription management + report access for FirstStrike YTC tab.

_YTC_CHANNEL_CONFIG = (
    Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    / "config"
    / "youtube_channels.json"
)  # noqa: E501


def _load_ytc_channels() -> list[dict]:
    """Load youtube_channels.json → list of channel dicts."""
    if not _YTC_CHANNEL_CONFIG.exists():
        return []
    try:
        data = json.loads(_YTC_CHANNEL_CONFIG.read_text())
        channels = data.get("channels", []) if isinstance(data, dict) else data
        # Normalise: accept both plain strings and {"url": ..., "name": ...} dicts
        result = []
        for ch in channels:
            if isinstance(ch, str):
                result.append(
                    {"url": ch, "name": ch.rstrip("/").split("@")[-1] if "@" in ch else ch}
                )  # noqa: E501
            elif isinstance(ch, dict):
                result.append(ch)
        return result
    except Exception:
        return []


def _save_ytc_channels(channels: list[dict]) -> None:
    """Persist channel list to youtube_channels.json."""
    _YTC_CHANNEL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    # Keep backwards-compat: write both "channels" (url strings) and "channel_details"
    payload = {
        "_comment": "Managed by YouTube Council API — follow/unfollow from FirstStrike.",
        "channels": [ch["url"] for ch in channels],
        "channel_details": channels,
    }
    _YTC_CHANNEL_CONFIG.write_text(json.dumps(payload, indent=2))


@router.get("/council/youtube/channels")
async def list_youtube_channels(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List all followed YouTube channels."""
    channels = _load_ytc_channels()
    return {"channels": channels, "count": len(channels)}


@router.post("/council/youtube/channels")
async def follow_youtube_channel(
    body: YouTubeChannelBody,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Follow a new YouTube channel."""
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="Channel URL required")

    # Normalise: ensure it looks like a YouTube channel URL
    if not url.startswith("http"):
        # Could be "@handle" or "handle" format
        handle = url.lstrip("@")
        url = f"https://www.youtube.com/@{handle}"

    channels = _load_ytc_channels()

    # Check for duplicates
    existing_urls = {ch["url"].lower().rstrip("/") for ch in channels}
    if url.lower().rstrip("/") in existing_urls:
        return {"status": "already_following", "channel": url}

    name = body.name.strip() or (url.rstrip("/").split("@")[-1] if "@" in url else url)
    new_channel = {
        "url": url,
        "name": name,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    channels.append(new_channel)
    _save_ytc_channels(channels)

    log.info(f"[YTC] Followed channel: {name} ({url})")
    return {"status": "followed", "channel": new_channel, "total": len(channels)}


@router.delete("/council/youtube/channels")
async def unfollow_youtube_channel(
    url: str = Query(..., description="Channel URL or handle to unfollow"),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Unfollow a YouTube channel."""
    url_clean = url.strip().lower().rstrip("/")
    if not url_clean:
        raise HTTPException(status_code=422, detail="Channel URL required")

    channels = _load_ytc_channels()
    before = len(channels)
    channels = [ch for ch in channels if ch["url"].lower().rstrip("/") != url_clean]
    after = len(channels)

    if before == after:
        raise HTTPException(status_code=404, detail=f"Channel not found: {url}")

    _save_ytc_channels(channels)
    log.info(f"[YTC] Unfollowed channel: {url}")
    return {"status": "unfollowed", "url": url, "remaining": after}


@router.get("/council/youtube/reports")
async def list_youtube_reports(
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List YouTube Council reports from intelligence-scan/council-reports/."""
    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    reports_dir = ncl_base / "intelligence-scan" / "council-reports"

    reports: list[dict] = []
    if reports_dir.exists():
        for rpt_path in sorted(
            reports_dir.glob("*youtube*.md"), key=lambda p: p.stat().st_mtime, reverse=True
        ):  # noqa: E501
            try:
                content = rpt_path.read_text(errors="replace")
                # Extract title from first heading
                title = rpt_path.stem.replace("-", " ").replace("_", " ").title()
                for line in content.split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break

                # Extract channel from content if present
                channel = "Unknown"
                for line in content.split("\n"):
                    if "channel:" in line.lower() or "source:" in line.lower():
                        channel = line.split(":", 1)[-1].strip()
                        break

                reports.append(
                    {
                        "filename": rpt_path.name,
                        "title": title,
                        "channel": channel,
                        "date": datetime.fromtimestamp(
                            rpt_path.stat().st_mtime, tz=timezone.utc
                        ).isoformat(),  # noqa: E501
                        "size_bytes": rpt_path.stat().st_size,
                        "status": "complete",
                    }
                )
            except Exception as e:
                log.warning(f"Failed to read report {rpt_path}: {e}")

            if len(reports) >= limit:
                break

    # Also check for JSON reports (newer format — per-video + rollup)
    json_reports_dir = ncl_base / "intelligence-scan" / "youtube-reports"
    if json_reports_dir.exists():
        for rpt_path in sorted(
            json_reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):  # noqa: E501
            try:
                data = json.loads(rpt_path.read_text())
                report_type = data.get("report_type", "legacy")  # per_video, rollup, or legacy
                # For per-video reports, extract video info from the videos list
                videos = data.get("videos", [])
                first_video = videos[0] if videos else {}
                entry = {
                    "filename": rpt_path.name,
                    "title": first_video.get(
                        "title", data.get("title", data.get("video_title", rpt_path.stem))
                    ),  # noqa: E501
                    "channel": first_video.get(
                        "channel", data.get("channel", data.get("channel_name", "Unknown"))
                    ),  # noqa: E501
                    "video_url": first_video.get("url", data.get("video_url", data.get("url", ""))),
                    "video_id": first_video.get("video_id", ""),
                    "date": data.get(
                        "completed_at",
                        data.get(
                            "published_at",
                            data.get(
                                "date",
                                datetime.fromtimestamp(
                                    rpt_path.stat().st_mtime, tz=timezone.utc
                                ).isoformat(),
                            ),
                        ),
                    ),  # noqa: E501
                    "transcript_summary": data.get("summary", data.get("transcript_summary", "")),
                    "analysis": data.get("raw_analysis", data.get("analysis", "")),
                    "insights_count": len(data.get("insights", [])),
                    "duration_hours": data.get("total_duration_hours", 0),
                    "status": data.get("status", "complete"),
                    "report_type": report_type,
                    "auto_triggered": data.get("auto_triggered", False),
                }
                if report_type == "rollup":
                    entry["per_video_count"] = data.get("per_video_count", len(videos))
                    entry["videos_processed"] = data.get("sources_processed", len(videos))
                reports.append(entry)
            except Exception as e:
                log.warning(f"Failed to read JSON report {rpt_path}: {e}")

            if len(reports) >= limit:
                break

    # Deduplicate by filename (MD and JSON dirs may reference the same report)
    seen_filenames: set[str] = set()
    deduped: list[dict] = []
    for r in reports:
        fn = r.get("filename", "")
        if fn not in seen_filenames:
            seen_filenames.add(fn)
            deduped.append(r)
    reports = deduped

    # Sort all by date descending
    reports.sort(key=lambda r: r.get("date", ""), reverse=True)
    return {"reports": reports[:limit], "count": len(reports[:limit])}


@router.get("/council/youtube/reports/{filename}")
async def get_youtube_report(
    filename: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get a specific YouTube Council report by filename."""
    # Security: prevent directory traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filename = safe_name

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))

    # Check both directories
    for reports_dir in [
        ncl_base / "intelligence-scan" / "council-reports",
        ncl_base / "intelligence-scan" / "youtube-reports",
    ]:
        rpt_path = reports_dir / filename
        if rpt_path.exists():
            content = rpt_path.read_text(errors="replace")
            if filename.endswith(".json"):
                try:
                    return {"report": json.loads(content), "filename": filename}
                except json.JSONDecodeError:
                    pass
            return {"report": {"content": content, "filename": filename}, "filename": filename}

    raise HTTPException(status_code=404, detail=f"Report not found: {filename}")


# YTC run status tracker — persists across requests
_ytc_run_status: dict[str, dict] = {}  # session_id → {status, step, started, error, ...}
_YTC_RUN_STATUS_MAX = 50  # Keep only the last N entries to prevent unbounded growth


@router.post("/council/youtube/run")
async def trigger_youtube_council(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Trigger a YouTube Council run (scrape → transcribe → analyze → report)."""
    # Prune old entries if we've hit the cap — keep only the most recent N-1
    if len(_ytc_run_status) >= _YTC_RUN_STATUS_MAX:
        # Sort by started_at, remove oldest entries
        sorted_ids = sorted(
            _ytc_run_status.keys(),
            key=lambda k: _ytc_run_status[k].get("started_at", ""),
        )
        for old_id in sorted_ids[: len(sorted_ids) - _YTC_RUN_STATUS_MAX + 1]:
            del _ytc_run_status[old_id]

    session_id = (
        f"ytc-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"  # noqa: E501
    )
    _ytc_run_status[session_id] = {
        "status": "running",
        "step": "starting",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "videos_found": 0,
        "videos_transcribed": 0,
        "insights": 0,
    }

    async def _run():
        status = _ytc_run_status[session_id]
        try:
            from ...councils.runner import run_youtube_council

            def _update_progress(step: str, **kwargs):
                status["step"] = step
                for k, v in kwargs.items():
                    status[k] = v

            status["step"] = "scraping"
            report = await run_youtube_council(session_id, progress_cb=_update_progress)
            if report:
                status["step"] = "saving"
                ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                json_dir = ncl_base / "intelligence-scan" / "youtube-reports"
                json_dir.mkdir(parents=True, exist_ok=True)
                out_path = json_dir / f"{session_id}.json"
                # Build a richer JSON so the iOS reports view has all the fields it needs
                report_data = {
                    "session_id": session_id,
                    "title": getattr(report, "title", "YouTube Council Report"),
                    "status": "complete",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "sources_processed": report.sources_processed,
                    "total_duration_hours": round(report.total_duration_hours, 2),
                    "summary": report.summary or "",
                    "transcript_summary": report.summary or "",
                    "analysis": report.raw_analysis or "",
                    "insights": [
                        {
                            "title": ins.title,
                            "description": ins.description,
                            "category": ins.category.value
                            if hasattr(ins.category, "value")
                            else str(ins.category),  # noqa: E501
                            "confidence": ins.confidence,
                            "tags": ins.tags,
                            "actionable": ins.actionable,
                            "action_suggestion": ins.action_suggestion or "",
                        }
                        for ins in (report.insights or [])
                    ],
                    "videos": [
                        {
                            "title": v.title,
                            "channel": v.channel,
                            "url": v.url,
                            "video_url": v.url,
                            "duration_seconds": v.duration_seconds,
                            "view_count": v.view_count,
                            "upload_date": v.upload_date,
                        }
                        for v in (report.videos or [])
                    ],
                }
                out_path.write_text(json.dumps(report_data, default=str, indent=2))
                status.update(
                    {
                        "status": "complete",
                        "step": "done",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "videos_transcribed": report.sources_processed,
                        "insights": len(report.insights),
                        "duration_hours": round(report.total_duration_hours, 2),
                    }
                )
                log.info(f"[YTC] Council run complete: {session_id}")
            else:
                status.update({"status": "complete", "step": "done (no new content)"})
                log.info(f"[YTC] Council run produced no report: {session_id}")
        except Exception as e:
            status.update({"status": "failed", "step": "error", "error": str(e)})
            log.exception(f"[YTC] Council run failed: {e}")

    task = asyncio.create_task(_run())
    task.add_done_callback(
        lambda t: log.error(f"YTC run died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )  # noqa: E501

    return {
        "session_id": session_id,
        "status": "running",
        "message": "YouTube Council pipeline started. Poll /council/youtube/status/{session_id} for progress.",  # noqa: E501
    }


@router.get("/council/youtube/status/{session_id}")
async def get_ytc_run_status(
    session_id: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get the current status of a YouTube Council run."""
    if session_id not in _ytc_run_status:
        raise HTTPException(status_code=404, detail=f"No run found: {session_id}")
    return {"session_id": session_id, **_ytc_run_status[session_id]}


# ── /councils/* — Council runner + reports + RAG + multi-agent ────────────


@router.post("/councils/run")
async def trigger_council_run(
    request: Request,
    body: CouncilRunRequest,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Trigger council runner to execute YouTube and/or X councils.

    The council runs in the background and returns immediately with a session ID.

    Args:
        body: CouncilRunRequest with council_type and dry_run flag

    Returns:
        Dict with session_id and status
    """
    from .. import routes as _routes

    _routes._check_rate_limit(request)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Validate council_type
    if body.council_type not in ("youtube", "x", "both"):
        raise HTTPException(
            status_code=400,
            detail="council_type must be 'youtube', 'x', or 'both'",
        )

    # Generate session ID
    session_id = (
        f"council-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"  # noqa: E501
    )

    # Define background task function
    async def run_council_background():
        try:
            from ...councils.runner import (  # noqa: I001
                run_youtube_council,
                run_x_council,
                run_both,
            )

            if body.council_type == "youtube":
                await run_youtube_council(session_id, dry_run=body.dry_run)
            elif body.council_type == "x":
                await run_x_council(session_id, dry_run=body.dry_run)
            else:  # both
                await run_both(session_id, dry_run=body.dry_run)

            # Log completion
            await brain._log_event(
                "council_run_complete",
                f"Council run ({body.council_type}) completed: {session_id}",
            )
        except Exception as e:
            log.exception(f"[/councils/run] council background task failed: {e}")
            await brain._log_event(
                "council_run_error",
                f"Council run ({body.council_type}) failed: {str(e)}",
            )

    task = asyncio.create_task(run_council_background())
    task.add_done_callback(
        lambda t: log.error(f"Council task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )  # noqa: E501

    return {
        "session_id": session_id,
        "council_type": body.council_type,
        "dry_run": body.dry_run,
        "status": "queued",
    }


@router.get("/councils/reports")
async def list_council_reports(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    List available council reports from the intelligence-scan/council-reports/ directory.

    Returns:
        Dict with list of report filenames, dates, and types
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Check multiple possible locations for council reports
    ncl_base = Path(brain.data_dir).parent
    project_root = Path(__file__).parent.parent.parent.parent  # NCL/runtime/api/routers → NCL
    candidates = [
        ncl_base / "intelligence-scan" / "council-reports",
        project_root / "intelligence-scan" / "council-reports",
        ncl_base / "data" / "council-reports",
        Path.home() / "dev" / "NCL" / "intelligence-scan" / "council-reports",
    ]
    reports_dir = None
    for c in candidates:
        if c.exists():
            reports_dir = c
            break

    reports = []

    if reports_dir:
        try:
            for report_file in sorted(reports_dir.glob("*.md"), reverse=True):
                fn = report_file.name
                stat = report_file.stat()
                # Read first 200 chars as preview
                try:
                    preview = report_file.read_text()[:200]
                except Exception as e:
                    log.debug("Could not read preview for report %s: %s", fn, e)
                    preview = ""
                report_entry = {
                    "filename": fn,
                    "path": str(report_file),
                    "size_bytes": stat.st_size,
                    "preview": preview,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
                # Enrich with JSON companion data if available
                json_companion = reports_dir / fn.replace(".md", ".json")
                if not json_companion.exists():
                    # Also try without the .md part
                    json_companion = reports_dir / (fn.rsplit(".", 1)[0] + ".json")
                if json_companion.exists():
                    try:
                        jdata = json.loads(json_companion.read_text())
                        if isinstance(jdata, dict):
                            report_entry["topic"] = jdata.get(
                                "summary", jdata.get("title", jdata.get("session_id", ""))
                            )  # noqa: E501
                            report_entry["summary"] = jdata.get("summary", "")
                            report_entry["session_id"] = jdata.get("session_id", "")
                            report_entry["channel_count"] = jdata.get(
                                "channels_analyzed", jdata.get("channel_count", 0)
                            )  # noqa: E501
                            report_entry["video_count"] = jdata.get(
                                "videos_processed", jdata.get("video_count", 0)
                            )  # noqa: E501
                            # Extract insight topics for better display
                            insights = jdata.get("insights", [])
                            if insights and isinstance(insights, list):
                                topics = []
                                for ins in insights[:3]:
                                    if isinstance(ins, dict):
                                        topics.append(ins.get("title", ins.get("topic", "")))
                                    elif isinstance(ins, str):
                                        topics.append(ins[:60])
                                report_entry["insight_topics"] = [t for t in topics if t]
                    except Exception:
                        pass
                reports.append(report_entry)
        except Exception as e:  # noqa: F841
            raise HTTPException(
                status_code=500,
                detail="Failed to list council reports",
            )
    else:
        return {
            "count": 0,
            "reports": [],
            "note": "No council reports directory found yet. Run a council session first.",
        }  # noqa: E501

    return {
        "count": len(reports),
        "reports": reports,
    }


@router.get("/councils/reports/{filename}")
async def get_council_report(
    filename: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Get the content of a specific council report.

    Args:
        filename: Report filename (e.g., 'PIPELINE-SIMULATION-2026-04-06.md')

    Returns:
        Dict with report content and metadata
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Security: prevent directory traversal
    safe_name = Path(filename).name  # strips any directory components
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filename = safe_name

    project_root = Path(__file__).parent.parent.parent.parent
    candidates = [
        Path(brain.data_dir).parent / "intelligence-scan" / "council-reports" / filename,
        project_root / "intelligence-scan" / "council-reports" / filename,
        Path.home() / "dev" / "NCL" / "intelligence-scan" / "council-reports" / filename,
    ]
    report_path = None
    for c in candidates:
        if c.exists():
            report_path = c
            break

    if not report_path:
        raise HTTPException(status_code=404, detail=f"Report not found: {filename}")

    try:
        async with aiofiles.open(report_path, "r") as f:
            content = await f.read()

        stat = report_path.stat()

        return {
            "filename": filename,
            "content": content,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
    except Exception as e:  # noqa: F841
        raise HTTPException(
            status_code=500,
            detail="Failed to read report",
        )


# ── Knowledge Base, Vector Store & Multi-Agent Endpoints ──────────────────

# Global singletons (lazy-initialized on first request).
# These are owned by this module; routes.py never referenced them outside
# the handler bodies we just moved.
_council_vector_store = None
_council_knowledge_base = None
_council_vector_store_lock: asyncio.Lock | None = None
_council_knowledge_base_lock: asyncio.Lock | None = None


def _get_council_vs_lock() -> asyncio.Lock:
    global _council_vector_store_lock
    if _council_vector_store_lock is None:
        _council_vector_store_lock = asyncio.Lock()
    return _council_vector_store_lock


def _get_council_kb_lock() -> asyncio.Lock:
    global _council_knowledge_base_lock
    if _council_knowledge_base_lock is None:
        _council_knowledge_base_lock = asyncio.Lock()
    return _council_knowledge_base_lock


@router.post("/councils/rag")
async def council_rag_query(
    req: RAGQueryRequest,
    _: None = Depends(verify_strike_token_dep),
):
    """
    Semantic search across all council knowledge (insights, transcripts, reports).

    Uses ChromaDB → LanceDB → TF-IDF fallback chain.
    """
    from .. import routes as _routes

    global _council_vector_store
    if not _council_vector_store:
        async with _get_council_vs_lock():
            if not _council_vector_store:
                from ...councils.shared.vector_store import CouncilVectorStore

                _council_vector_store = CouncilVectorStore(data_dir=_routes.config.data_dir)
                await _council_vector_store.init()

    results = await _council_vector_store.query(
        query_text=req.query,
        top_k=req.top_k,
        filter_type=req.filter_type,
        filter_source=req.filter_source,
    )
    return {
        "query": req.query,
        "total": len(results),
        "backend": _council_vector_store._backend,
        "results": [r.to_dict() for r in results],
    }


@router.get("/councils/knowledge-base/stats")
async def knowledge_base_stats(_: None = Depends(verify_strike_token_dep)):
    """Return knowledge base statistics."""
    global _council_knowledge_base
    if not _council_knowledge_base:
        async with _get_council_kb_lock():
            if not _council_knowledge_base:
                from ...councils.shared.knowledge_base import KnowledgeBase

                _council_knowledge_base = KnowledgeBase()

    return _council_knowledge_base.get_stats()


@router.get("/councils/vector-store/stats")
async def vector_store_stats(_: None = Depends(verify_strike_token_dep)):
    """Return vector store statistics."""
    from .. import routes as _routes

    global _council_vector_store
    if not _council_vector_store:
        async with _get_council_vs_lock():
            if not _council_vector_store:
                from ...councils.shared.vector_store import CouncilVectorStore

                _council_vector_store = CouncilVectorStore(data_dir=_routes.config.data_dir)
                await _council_vector_store.init()

    return _council_vector_store.get_stats()


@router.post("/councils/vector-store/backfill")
async def vector_store_backfill(_: None = Depends(verify_strike_token_dep)):
    """
    Backfill the council vector store from existing council report files.
    Reads all reports from the council-reports directory and indexes their
    content into ChromaDB for RAG retrieval.
    """
    from .. import routes as _routes

    global _council_vector_store
    if not _council_vector_store:
        async with _get_council_vs_lock():
            if not _council_vector_store:
                from ...councils.shared.vector_store import CouncilVectorStore

                _council_vector_store = CouncilVectorStore(data_dir=_routes.config.data_dir)
                await _council_vector_store.init()

    # Try multiple possible report locations
    ncl_root = Path(_routes.config.data_dir).parent
    candidates = [
        ncl_root / "intelligence-scan" / "council-reports",
        Path.home() / "dev" / "NCL" / "intelligence-scan" / "council-reports",
        ncl_root / "data" / "councils",
    ]
    reports_dir = None
    for c in candidates:
        if c.exists():
            reports_dir = c
            break
    if not reports_dir:
        return {"status": "no_reports_dir", "indexed": 0, "tried": [str(c) for c in candidates]}

    indexed = 0
    errors = []
    for report_file in sorted(reports_dir.glob("*.md")):
        try:
            content = report_file.read_text("utf-8")
            # Extract session ID from filename
            session_id = report_file.stem
            # Determine source from filename
            source = "x" if "x-council" in report_file.name else "youtube"

            # Extract summary (first ~2000 chars after Executive Summary heading)
            summary = content[:3000]
            lines = content.split("\n")
            exec_start = None
            for i, line in enumerate(lines):
                if "Executive Summary" in line:
                    exec_start = i + 1
                    break
            if exec_start:
                summary_lines = []
                for line in lines[exec_start : exec_start + 40]:
                    if line.startswith("## ") and summary_lines:
                        break
                    summary_lines.append(line)
                summary = "\n".join(summary_lines).strip()

            # Index the report summary
            await _council_vector_store.index_report_summary(
                session_id=session_id,
                source=source,
                summary=summary,
                insight_count=0,
            )

            # Also index the full report in chunks for deeper retrieval
            chunk_size = 1500
            for i in range(0, min(len(content), 15000), chunk_size):
                chunk = content[i : i + chunk_size]
                if len(chunk.strip()) < 50:
                    continue
                doc_id = f"report-chunk-{session_id}-{i // chunk_size}"
                await _council_vector_store.index_document(
                    doc_id=doc_id,
                    text=chunk,
                    metadata={
                        "type": "report_chunk",
                        "source": source,
                        "session_id": session_id,
                        "chunk_index": i // chunk_size,
                    },
                )
            indexed += 1
        except Exception as e:
            errors.append(f"{report_file.name}: {str(e)}")

    stats = _council_vector_store.get_stats()
    return {
        "status": "ok",
        "reports_indexed": indexed,
        "vector_store_docs": stats.get("documents", 0),
        "backend": stats.get("backend", "unknown"),
        "errors": errors,
    }


@router.post("/councils/multi-agent")
async def run_multi_agent_council(
    request: Request,
    req: MultiAgentRequest,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
):
    """
    Run multi-agent council analysis (Analyst → Researcher → Strategist → Synthesizer).

    Each role uses its preferred AI model with fallback chain.
    Runs in background and returns session ID.
    """
    from .. import routes as _routes

    _routes._check_rate_limit(request)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    session_id = (
        f"multi-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"  # noqa: E501
    )

    async def run_orchestrator_background():
        from ...councils.shared.orchestrator import run_multi_agent_analysis

        try:
            result = await run_multi_agent_analysis(
                source_material=req.source_material,
                session_id=session_id,
                pipeline=req.pipeline,
            )
            await brain._log_event(
                "multi_agent_council_complete",
                f"Multi-agent council ({req.pipeline}) complete: {len(result.insights_json)} insights, "  # noqa: E501
                f"{result.duration_seconds:.1f}s, models: {result.models_used}",
                metadata={
                    "session_id": session_id,
                    "pipeline": req.pipeline,
                    "insights_count": len(result.insights_json),
                    "agents_run": len(result.agents_run),
                    "models_used": result.models_used,
                    "duration_seconds": result.duration_seconds,
                },
            )
        except Exception as e:
            log.exception(f"[/councils/multi-agent] background task failed: {e}")
            await brain._log_event(
                "multi_agent_council_error",
                f"Multi-agent council failed: {e}",
            )

    task = asyncio.create_task(run_orchestrator_background())
    task.add_done_callback(
        lambda t: log.error(f"Multi-agent task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )  # noqa: E501

    return {
        "session_id": session_id,
        "pipeline": req.pipeline,
        "agents": ["Insight Analyst", "Deep Researcher", "Strategist", "Synthesizer"],
        "status": "queued",
    }


@router.get("/councils/status")
async def councils_status(
    council_store=Depends(get_council_store),
    replay_engine=Depends(get_replay_engine),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Council system status — active sessions, store health, and recent activity.

    Distinct from /councils/reports which returns full report files.
    """
    status: dict = {"status": "ok"}

    # Council store stats — owned by routes.py until W5-06 retires
    # ``runtime/council_runner/`` and moves the store into council_pack.
    if council_store:
        try:
            recent = council_store.list_runs(limit=5)
            status["recent_runs"] = len(recent)
            status["latest_run"] = recent[0].model_dump() if recent else None
            status["store"] = "connected"
        except Exception as e:
            status["store"] = f"error: {e}"
    else:
        status["store"] = "not_initialized"

    # Replay engine
    status["replay_engine"] = "available" if replay_engine else "not_initialized"

    # Autonomous council flags
    if autonomous:
        try:
            flags = await autonomous._get_council_flags()
            status["pending_council_flags"] = len(flags)
        except Exception:
            status["pending_council_flags"] = 0
    else:
        status["pending_council_flags"] = 0

    return status
