"""Night Watch endpoints — parse and surface the nightly maintenance brief.

Wave 14A (2026-05-25): Night Watch produces one human-readable artifact per
night at `data/night-watch/daily-YYYY-MM-DD.md` containing a STATUS pill +
KEY FINDINGS + COST REPORT + SYSTEM HEALTH + RECOMMENDATIONS + raw-data
appendix. Before this wave the only consumer was the ntfy push.

These endpoints parse that markdown into a structured payload so the
FirstStrike iOS app (and any future client) can render it.

Routes:
    GET /intelligence/night-watch/latest       — most recent brief (today, else yesterday, else newest)
    GET /intelligence/night-watch/by-date/{d}  — specific YYYY-MM-DD brief
    GET /intelligence/night-watch/history      — recent briefs list (lightweight)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ...deps import verify_strike_token_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["intel-night-watch"])


# Same directory the autonomous scheduler writes to. Resolved lazily so
# tests can override via NCL_DATA without import-time freeze.
#
# Path resolution: prefer NCL_DATA env var, fall back to the repo's `data/`
# directory derived from THIS file's location (runtime/api/routers/intel/),
# which is the actual runtime layout. The `Path.home() / "NCL" / "data"`
# default used elsewhere in this file is stale (real path is ~/dev/NCL/data);
# this resolver does the right thing without relying on a misconfigured env.
def _night_watch_dir() -> Path:
    override = os.getenv("NCL_DATA")
    if override:
        return Path(override) / "night-watch"
    repo_root = Path(__file__).resolve().parents[4]  # intel → routers → api → runtime → repo
    return repo_root / "data" / "night-watch"


# Headed sections in the analyst brief. Order matters for parsing (we slice
# the source between sequential headers).
_NARRATIVE_HEADERS = (
    "KEY FINDINGS",
    "COST REPORT",
    "SYSTEM HEALTH",
    "RECOMMENDATIONS",
)

_STATUS_PATTERN = re.compile(r"^\s*STATUS:\s*(GREEN|YELLOW|RED|UNKNOWN)\s*$", re.MULTILINE | re.IGNORECASE)
_GENERATED_PATTERN = re.compile(r"^\s*Generated:\s*(\S+)\s*$", re.MULTILINE)
_COST_PATTERN = re.compile(r"^\s*LLM cost:\s*\$([\d.]+)\s*$", re.MULTILINE)
_RAW_SECTION_PATTERN = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_CODE_FENCE_PATTERN = re.compile(r"```(?:\w+)?\n(.*?)\n```", re.DOTALL)


def _strip_bullet(line: str) -> str:
    """Strip leading bullet/number markers from a line."""
    return re.sub(r"^\s*(?:[-*•]|\d+\.)\s+", "", line).strip()


def _extract_bullets(text: str) -> list[str]:
    """Extract bullet/numbered items from a section, preserving order.

    Lines that don't look like list items become their own paragraph entries
    so we don't silently drop free-form prose the LLM occasionally emits.
    """
    items: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if buf:
                items.append(" ".join(buf).strip())
                buf = []
            continue
        # New list item starts → flush previous, start new
        if re.match(r"^\s*(?:[-*•]|\d+\.)\s+", line):
            if buf:
                items.append(" ".join(buf).strip())
                buf = []
            buf.append(_strip_bullet(line))
        else:
            # continuation of current item
            if buf:
                buf.append(line.strip())
            else:
                # Free-form prose line — keep as standalone entry
                items.append(line.strip())
    if buf:
        items.append(" ".join(buf).strip())
    # Drop horizontal-rule artifacts (markdown section separators that sneak
    # in when a section's body abuts a `---` line before the raw-data appendix)
    return [i for i in items if i and not re.fullmatch(r"[-=*]{3,}", i)]


def _section_slice(narrative: str, name: str) -> str:
    """Return the body of the named section (header excluded)."""
    upper = narrative.upper()
    start_marker = f"{name}:"
    start = upper.find(start_marker)
    if start < 0:
        return ""
    body_start = start + len(start_marker)
    # Find the next known header after this one
    next_at = len(narrative)
    for other in _NARRATIVE_HEADERS:
        if other == name:
            continue
        idx = upper.find(f"{other}:", body_start)
        if idx > 0 and idx < next_at:
            next_at = idx
    # Also stop at the raw-data appendix
    raw_at = narrative.find("## Raw Data", body_start)
    if raw_at > 0 and raw_at < next_at:
        next_at = raw_at
    return narrative[body_start:next_at].strip()


def _parse_raw_appendix(markdown: str) -> dict:
    """Parse the `## Raw Data Collected` appendix into a dict of section_name → text/code."""
    appendix_match = re.search(r"##\s+Raw Data Collected\s*\n(.*)$", markdown, re.DOTALL)
    if not appendix_match:
        return {}
    appendix = appendix_match.group(1)
    sections: dict[str, str] = {}
    headers = list(_RAW_SECTION_PATTERN.finditer(appendix))
    for i, h in enumerate(headers):
        name = h.group(1).strip().lower().replace(" ", "_")
        body_start = h.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(appendix)
        body = appendix[body_start:body_end].strip()
        # Prefer the code-fence contents if present
        fence = _CODE_FENCE_PATTERN.search(body)
        if fence:
            sections[name] = fence.group(1).strip()
        else:
            sections[name] = body
    return sections


def _parse_brief(path: Path) -> dict:
    """Parse a daily-YYYY-MM-DD.md into the iOS-consumable payload."""
    if not path.exists():
        raise FileNotFoundError(str(path))

    raw = path.read_text(encoding="utf-8")

    # Date from filename, generated timestamp from body
    date_match = re.search(r"daily-(\d{4}-\d{2}-\d{2})\.md", path.name)
    date_str = date_match.group(1) if date_match else ""

    generated_at = ""
    if (m := _GENERATED_PATTERN.search(raw)):
        generated_at = m.group(1).strip()

    llm_cost_usd = 0.0
    if (m := _COST_PATTERN.search(raw)):
        try:
            llm_cost_usd = float(m.group(1))
        except ValueError:
            llm_cost_usd = 0.0

    status = "UNKNOWN"
    if (m := _STATUS_PATTERN.search(raw)):
        status = m.group(1).upper()

    # Narrative = everything before the raw-data appendix
    narrative_end = raw.find("## Raw Data")
    narrative = raw[:narrative_end] if narrative_end > 0 else raw

    sections_text = {name: _section_slice(narrative, name) for name in _NARRATIVE_HEADERS}

    return {
        "date": date_str,
        "generated_at": generated_at,
        "status": status,
        "llm_cost_usd": llm_cost_usd,
        "key_findings": _extract_bullets(sections_text["KEY FINDINGS"]),
        "cost_report": _extract_bullets(sections_text["COST REPORT"]),
        "system_health": _extract_bullets(sections_text["SYSTEM HEALTH"]),
        "recommendations": _extract_bullets(sections_text["RECOMMENDATIONS"]),
        "raw_appendix": _parse_raw_appendix(raw),
        "markdown_full": raw,
        "source_file": str(path),
    }


@router.get("/intelligence/night-watch/latest")
async def night_watch_latest(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Most recent Night Watch brief.

    Tries today first, then yesterday, then falls back to the newest .md on
    disk (handles the case where Brain was down at 2am ET and no fresh brief
    was generated overnight).
    """
    nw_dir = _night_watch_dir()
    if not nw_dir.exists():
        return {"status": "not_found", "message": f"Night Watch directory missing: {nw_dir}"}

    today_dt = datetime.now(timezone.utc)
    today = today_dt.strftime("%Y-%m-%d")
    yesterday = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    candidate_today = nw_dir / f"daily-{today}.md"
    if candidate_today.exists():
        try:
            payload = _parse_brief(candidate_today)
            payload["freshness"] = "today"
            return payload
        except Exception as e:  # pragma: no cover
            log.warning("Failed to parse today's night-watch brief: %s", e)

    candidate_yest = nw_dir / f"daily-{yesterday}.md"
    if candidate_yest.exists():
        try:
            payload = _parse_brief(candidate_yest)
            payload["freshness"] = "yesterday"
            return payload
        except Exception as e:  # pragma: no cover
            log.warning("Failed to parse yesterday's night-watch brief: %s", e)

    # Fall back to newest .md by mtime
    md_files = sorted(nw_dir.glob("daily-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not md_files:
        return {
            "status": "not_found",
            "message": "No Night Watch briefs on disk. Loop runs at 2am ET nightly.",
            "checked": str(nw_dir),
        }
    try:
        payload = _parse_brief(md_files[0])
        payload["freshness"] = "stale"
        return payload
    except Exception as e:
        log.exception("Failed to parse newest night-watch brief: %s", e)
        raise HTTPException(status_code=500, detail=f"Parse failure: {e}")


@router.get("/intelligence/night-watch/by-date/{date}")
async def night_watch_by_date(
    date: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """A specific date's Night Watch brief."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    path = _night_watch_dir() / f"daily-{date}.md"
    if not path.exists():
        return {"status": "not_found", "date": date, "message": f"No Night Watch brief for {date}"}
    try:
        return _parse_brief(path)
    except Exception as e:
        log.exception("Failed to parse %s: %s", path, e)
        raise HTTPException(status_code=500, detail=f"Parse failure: {e}")


@router.get("/intelligence/night-watch/history")
async def night_watch_history(
    limit: int = Query(default=14, ge=1, le=60, description="Max briefs to return"),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Lightweight history — date + status + key_findings count + cost, newest first.

    Cheap enough to drive a list view; clients fetch full content via
    /night-watch/by-date/{d} when a row is tapped.
    """
    nw_dir = _night_watch_dir()
    if not nw_dir.exists():
        return {"status": "not_found", "items": [], "message": f"Night Watch directory missing: {nw_dir}"}

    md_files = sorted(nw_dir.glob("daily-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    items: list[dict] = []
    for path in md_files[:limit]:
        try:
            full = _parse_brief(path)
        except Exception as e:  # pragma: no cover
            log.warning("Skipping unparseable %s: %s", path, e)
            continue
        items.append(
            {
                "date": full["date"],
                "generated_at": full["generated_at"],
                "status": full["status"],
                "llm_cost_usd": full["llm_cost_usd"],
                "key_findings_count": len(full["key_findings"]),
                "recommendations_count": len(full["recommendations"]),
                "source_file": full["source_file"],
            }
        )

    return {"status": "ok", "items": items, "count": len(items), "limit": limit}
