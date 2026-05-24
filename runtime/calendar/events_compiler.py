"""
Unified events compiler — merges every Brain subsystem that produces a
time-anchored item with market + local city events into one normalized
stream consumed by the Calendar Agent / iOS.

Sources pulled:
  1. predictions   — data/predictions/*.json (target/expires)
  2. council       — intelligence-scan/council-reports/*.json
  3. scanner       — intelligence-scan/signals/*.jsonl (Awarebot tier)
  4. portfolio     — held tickers -> Finnhub earnings calendar
  5. intel         — intelligence-scan/council-reports/WAR_ROOM_*.json
  6. journal       — data/journal/journal.jsonl entries with due_date

Plus, for compile_unified_events:
  - market   — runtime.calendar.events.get_all_events
  - local    — runtime.calendar.local_events.get_local_events

Normalized event schema — every record from every source is shaped into
this dict so iOS only deals with one type:

  {
    "id":            str,                # sha256(source + source_id + date)
    "date":          str,                # YYYY-MM-DD
    "time":          str | None,         # HH:MM if known
    "datetime_utc":  str,                # ISO8601 with tz
    "title":         str,                # human-readable
    "description":   str,                # 1-2 sentence detail
    "source":        str,                # prediction|council|scanner|portfolio|intel|journal|market|local|moon|sun
    "source_id":     str,                # original id from source system
    "category":      str,                # source-specific subtype
    "impact":        str,                # low|medium|high|critical
    "tickers":       list[str],          # for dedup
    "entities":      list[str],          # other entity names
    "url":           str | None,         # back to source
    "raw":           dict,               # original payload
  }
"""  # noqa: E501

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx


log = logging.getLogger("ncl.calendar.events_compiler")

# ── Repo / data root resolution ───────────────────────────────────────
# This module sits at runtime/calendar/events_compiler.py -> ../../
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_ROOT = _REPO_ROOT / "data"
_INTEL_ROOT = _REPO_ROOT / "intelligence-scan"

_PREDICTIONS_DIR = _DATA_ROOT / "predictions"
_JOURNAL_FILE = _DATA_ROOT / "journal" / "journal.jsonl"
_COUNCIL_REPORTS_DIR = _INTEL_ROOT / "council-reports"
_SCANNER_SIGNALS_DIR = _INTEL_ROOT / "signals"

# Cache
_CACHE_DIR = _DATA_ROOT / "calendar"
_CACHE_FILE = _CACHE_DIR / "compiled_events_cache.jsonl"
_CACHE_TTL_SECONDS = 600  # 10 minutes

# In-process cache mirror so repeated calls in the same process are even faster.
# Key -> (timestamp_epoch, list[dict])
_mem_cache: dict[str, tuple[float, list[dict]]] = {}

# Background-refresh task registry (avoid spawning multiple refreshers per key)
_refresh_tasks: dict[str, asyncio.Task] = {}

# Dollar-sign / contextual ticker regex (mirrors memory entity extractor)
_TICKER_RX = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_CTX_RX = re.compile(
    r"\b([A-Z]{2,5})\b\s+(?:stock|shares|ticker|price|calls|puts|earnings)",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _make_event_id(source: str, source_id: str, date_str: str) -> str:
    h = hashlib.sha256(f"{source}|{source_id}|{date_str}".encode()).hexdigest()
    return h[:32]


def _to_iso_utc(d: date, t: Optional[str] = None) -> str:
    if t:
        try:
            hh, mm = [int(x) for x in t.split(":")[:2]]
        except Exception:
            hh, mm = 0, 0
    else:
        hh, mm = 0, 0
    dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc)
    return dt.isoformat()


def _coerce_date(value: Any) -> Optional[date]:
    """Pull a date out of multiple representations gracefully."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Try ISO8601 with tz, then plain YYYY-MM-DD
    for fmt in (None, "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            if fmt is None:
                # datetime.fromisoformat handles offsets and Z (Py3.11+)
                s2 = s.replace("Z", "+00:00")
                return datetime.fromisoformat(s2).date()
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _extract_tickers(text: str) -> list[str]:
    if not text:
        return []
    found = set()
    for m in _TICKER_RX.findall(text):
        found.add(m.upper())
    for m in _TICKER_CTX_RX.findall(text):
        found.add(m.upper())
    return sorted(found)


def _normalize(
    *,
    source: str,
    source_id: str,
    event_date: date,
    title: str,
    description: str = "",
    time_str: Optional[str] = None,
    category: str = "",
    impact: str = "low",
    tickers: Optional[list[str]] = None,
    entities: Optional[list[str]] = None,
    url: Optional[str] = None,
    raw: Optional[dict] = None,
) -> dict:
    date_str = event_date.isoformat()
    return {
        "id": _make_event_id(source, source_id, date_str),
        "date": date_str,
        "time": time_str,
        "datetime_utc": _to_iso_utc(event_date, time_str),
        "title": title[:300],
        "description": (description or "")[:1000],
        "source": source,
        "source_id": source_id,
        "category": category or source,
        "impact": impact if impact in ("low", "medium", "high", "critical") else "low",
        "tickers": tickers or [],
        "entities": entities or [],
        "url": url,
        "raw": raw or {},
    }


def _in_range(d: date, start: date, end: date) -> bool:
    return start <= d <= end


# ─────────────────────────────────────────────────────────────────────
# Source pullers
# ─────────────────────────────────────────────────────────────────────


async def _pull_predictions(start: date, end: date) -> list[dict]:
    """Read every prediction json blob and map its target/expiry to an event."""
    events: list[dict] = []
    if not _PREDICTIONS_DIR.is_dir():
        return events

    for fp in sorted(_PREDICTIONS_DIR.glob("pred-*.json")):
        try:
            data = json.loads(fp.read_text())
        except Exception as e:
            log.debug("predictions: skip %s (%s)", fp.name, e)
            continue

        # Prefer explicit target_date / expires_at, else parse from consensus
        target = (
            _coerce_date(data.get("target_date"))
            or _coerce_date(data.get("expires_at"))
            or _coerce_date(data.get("deadline"))
        )
        if not target:
            # Fall back to timestamp + 14 day default review window
            ts = _coerce_date(data.get("timestamp"))
            if not ts:
                continue
            target = ts + timedelta(days=14)

        if not _in_range(target, start, end):
            continue

        topic = data.get("topic", "general")
        conf = data.get("confidence")
        consensus_blurb = (data.get("consensus") or "")[:400]

        impact = "low"
        if isinstance(conf, (int, float)):
            if conf >= 0.7:
                impact = "high"
            elif conf >= 0.4:
                impact = "medium"

        source_id = fp.stem
        events.append(
            _normalize(
                source="prediction",
                source_id=source_id,
                event_date=target,
                title=f"Review prediction: {topic}",
                description=f"Outcome due. {consensus_blurb}",
                category=topic,
                impact=impact,
                tickers=_extract_tickers(consensus_blurb),
                raw={
                    "topic": topic,
                    "confidence": conf,
                    "timestamp": data.get("timestamp"),
                },
            )
        )

    log.info("compiler: predictions pulled=%d (range %s..%s)", len(events), start, end)
    return events


async def _pull_council(start: date, end: date) -> list[dict]:
    """Council reports — schedule a review event on each report's day."""
    events: list[dict] = []
    if not _COUNCIL_REPORTS_DIR.is_dir():
        return events

    for fp in sorted(_COUNCIL_REPORTS_DIR.glob("*.json")):
        # Skip war-room briefings here — handled by _pull_intel
        if fp.name.startswith("WAR_ROOM_"):
            continue

        try:
            data = json.loads(fp.read_text())
        except Exception as e:
            log.debug("council: skip %s (%s)", fp.name, e)
            continue

        ts = _coerce_date(data.get("timestamp"))
        if not ts:
            continue
        if not _in_range(ts, start, end):
            continue

        ctype = data.get("council_type", "council")
        session = data.get("session_id", fp.stem)
        insights = data.get("insights") or []

        top = insights[0] if insights else {}
        title = top.get("title") or f"{ctype.upper()} council — {session}"
        desc = (top.get("description") or top.get("action_suggestion") or "")[:400]
        impact = "high" if top.get("actionable") else "medium"

        tickers: set[str] = set()
        for ins in insights[:5]:
            for tag in ins.get("tags", []) or []:
                if isinstance(tag, str) and tag.isupper() and 1 <= len(tag) <= 5:
                    tickers.add(tag)

        events.append(
            _normalize(
                source="council",
                source_id=session,
                event_date=ts,
                title=f"Execute council decision: {title}"[:300],
                description=desc,
                category=ctype,
                impact=impact,
                tickers=sorted(tickers),
                raw={"council_type": ctype, "insight_count": len(insights)},
            )
        )

    log.info("compiler: council pulled=%d (range %s..%s)", len(events), start, end)
    return events


async def _pull_scanner(start: date, end: date) -> list[dict]:
    """High-tier signals from the last 48h that reference dates inside our window."""
    events: list[dict] = []
    if not _SCANNER_SIGNALS_DIR.is_dir():
        return events

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    time_tag_rx = re.compile(
        r"\b(earnings|fomc|cpi|nfp|gdp|expiry|launch|release|deadline|embargo)\b",
        re.IGNORECASE,
    )

    for fp in sorted(_SCANNER_SIGNALS_DIR.glob("signals-*.jsonl")):
        try:
            with fp.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                    except Exception:
                        continue
                    ts_str = sig.get("timestamp")
                    ts = _coerce_date(ts_str)
                    if not ts:
                        continue
                    # filter recency
                    try:
                        ts_dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                        if ts_dt < cutoff:
                            continue
                    except Exception:
                        pass

                    importance = sig.get("importance_score", 0) or 0
                    desc = sig.get("description", "") or ""
                    title = sig.get("title", "") or ""
                    if importance < 70 and not time_tag_rx.search(f"{title} {desc}"):
                        continue
                    if not _in_range(ts, start, end):
                        continue

                    impact = (
                        "critical" if importance >= 90 else "high" if importance >= 75 else "medium"
                    )
                    sid = sig.get("signal_id") or sig.get("id") or fp.name
                    events.append(
                        _normalize(
                            source="scanner",
                            source_id=str(sid),
                            event_date=ts,
                            title=title[:300] or "Scanner signal",
                            description=desc,
                            category=sig.get("category", "signal"),
                            impact=impact,
                            tickers=_extract_tickers(f"{title} {desc}"),
                            entities=list(sig.get("convergence_tags") or []),
                            url=sig.get("url"),
                            raw={"importance_score": importance},
                        )
                    )
        except Exception as e:
            log.debug("scanner: skip %s (%s)", fp.name, e)

    log.info("compiler: scanner pulled=%d (range %s..%s)", len(events), start, end)
    return events


async def _pull_portfolio(start: date, end: date) -> list[dict]:
    """Earnings dates for currently-held tickers via Finnhub."""
    events: list[dict] = []
    tickers: list[str] = []

    # Try to get held tickers from the injected PortfolioManager (Brain runtime).
    try:
        from runtime.portfolio import portfolio_routes  # type: ignore

        pm = getattr(portfolio_routes, "_portfolio_manager", None)
        if pm is not None:
            positions = pm.get_positions()
            for p in positions:
                sym = p.get("symbol")
                if isinstance(sym, str) and sym:
                    tickers.append(sym.split(":")[0].split(" ")[0].upper())
    except Exception as e:
        log.debug("portfolio: no PortfolioManager available (%s)", e)

    # Dedup + cap
    tickers = sorted({t for t in tickers if t})[:25]
    if not tickers:
        log.info("compiler: portfolio pulled=0 (no held tickers)")
        return events

    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        log.info("compiler: portfolio pulled=0 (no FINNHUB_API_KEY)")
        return events

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            for sym in tickers:
                try:
                    resp = await client.get(
                        "https://finnhub.io/api/v1/calendar/earnings",
                        params={
                            "from": start.isoformat(),
                            "to": end.isoformat(),
                            "symbol": sym,
                            "token": api_key,
                        },
                    )
                    if resp.status_code != 200:
                        continue
                    payload = resp.json()
                    for row in payload.get("earningsCalendar", []) or []:
                        d = _coerce_date(row.get("date"))
                        if not d or not _in_range(d, start, end):
                            continue
                        events.append(
                            _normalize(
                                source="portfolio",
                                source_id=f"earnings:{sym}:{d.isoformat()}",
                                event_date=d,
                                title=f"{sym} Earnings",
                                description=(
                                    f"EPS est={row.get('epsEstimate')}, "
                                    f"rev est={row.get('revenueEstimate')}, "
                                    f"hour={row.get('hour', 'unknown')}"
                                ),
                                category="earnings",
                                impact="high",
                                tickers=[sym],
                                raw=row,
                            )
                        )
                except Exception as e:
                    log.debug("portfolio: finnhub fail for %s (%s)", sym, e)
    except Exception as e:
        log.warning("portfolio: finnhub batch failed: %s", e)

    log.info(
        "compiler: portfolio pulled=%d (tickers=%d, range %s..%s)",
        len(events),
        len(tickers),
        start,
        end,
    )
    return events


async def _pull_intel(start: date, end: date) -> list[dict]:
    """Intel briefs (WAR_ROOM_BRIEFING_*) from the last 7 days."""
    events: list[dict] = []
    if not _COUNCIL_REPORTS_DIR.is_dir():
        return events

    cutoff = date.today() - timedelta(days=7)
    for fp in sorted(_COUNCIL_REPORTS_DIR.glob("WAR_ROOM_BRIEFING_*.json")):
        try:
            data = json.loads(fp.read_text())
        except Exception as e:
            log.debug("intel: skip %s (%s)", fp.name, e)
            continue

        ts = _coerce_date(data.get("timestamp")) or _coerce_date(data.get("reference_date"))
        if not ts:
            continue
        if ts < cutoff:
            continue
        if not _in_range(ts, start, end):
            continue

        title = data.get("title") or data.get("session_id") or fp.stem
        summary = (data.get("executive_summary") or data.get("summary") or "")[:400]
        events.append(
            _normalize(
                source="intel",
                source_id=fp.stem,
                event_date=ts,
                title=f"Intel brief: {title}"[:300],
                description=summary,
                category="war_room",
                impact="medium",
                raw={"file": fp.name},
            )
        )

    log.info("compiler: intel pulled=%d (range %s..%s)", len(events), start, end)
    return events


async def _pull_journal(start: date, end: date) -> list[dict]:
    """Journal entries with a `due_date` field land on that date as a commitment."""
    events: list[dict] = []
    if not _JOURNAL_FILE.is_file():
        return events

    try:
        with _JOURNAL_FILE.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue

                due = _coerce_date(entry.get("due_date"))
                if not due:
                    continue
                if not _in_range(due, start, end):
                    continue

                eid = entry.get("entry_id") or entry.get("id") or f"journal-{due.isoformat()}"
                title = entry.get("title") or "Journal commitment"
                content = (entry.get("content") or "")[:400]
                impact = "high" if (entry.get("importance") or 0) >= 0.7 else "medium"

                events.append(
                    _normalize(
                        source="journal",
                        source_id=eid,
                        event_date=due,
                        title=title[:300],
                        description=content,
                        category=entry.get("entry_type", "note"),
                        impact=impact,
                        tickers=_extract_tickers(f"{title} {content}"),
                        entities=list(entry.get("tags") or []),
                        raw={"importance": entry.get("importance")},
                    )
                )
    except Exception as e:
        log.warning("journal: read failed (%s)", e)

    log.info("compiler: journal pulled=%d (range %s..%s)", len(events), start, end)
    return events


# ─────────────────────────────────────────────────────────────────────
# Market + local adapters (use existing normalized-ish modules)
# ─────────────────────────────────────────────────────────────────────


def _normalize_market_event(ev: dict) -> Optional[dict]:
    """Adapt runtime.calendar.events.get_all_events() output to schema."""
    d = _coerce_date(ev.get("date"))
    if not d:
        return None
    title = ev.get("title", "Market event")
    desc = ev.get("description", "")
    impact = ev.get("impact", "low")
    cat = ev.get("category", "economic")
    src_id = f"{cat}:{d.isoformat()}:{title[:50]}"
    return _normalize(
        source="market",
        source_id=src_id,
        event_date=d,
        title=title,
        description=desc,
        time_str=(ev.get("time") or None) if not ev.get("all_day") else None,
        category=cat,
        impact=impact,
        tickers=_extract_tickers(f"{title} {desc}"),
        url=ev.get("url"),
        raw=ev,
    )


def _normalize_local_event(ev: dict, city_id: str) -> Optional[dict]:
    """Adapt runtime.calendar.local_events.get_local_events() output to schema."""
    d = _coerce_date(ev.get("date"))
    if not d:
        return None
    title = ev.get("title", "Local event")
    desc = ev.get("description", "")
    impact = ev.get("impact", "low")
    cat = ev.get("category", "local")
    venue = ev.get("venue", "")
    src_id = f"{city_id}:{cat}:{d.isoformat()}:{title[:50]}:{venue[:30]}"
    return _normalize(
        source="local",
        source_id=src_id,
        event_date=d,
        title=title,
        description=desc,
        time_str=(ev.get("time") or None),
        category=cat,
        impact=impact,
        url=ev.get("url"),
        raw=ev,
    )


# ─────────────────────────────────────────────────────────────────────
# Cache (file + in-memory)
# ─────────────────────────────────────────────────────────────────────


def _cache_key(city_id: str, start: date, end: date) -> str:
    return f"{city_id}_{start.isoformat()}_{end.isoformat()}"


async def get_cached_compile(
    city_id: str,
    start: date,
    end: date,
) -> Optional[list[dict]]:
    """Return cached events (with optional `stale: true` flag) or None."""
    key = _cache_key(city_id, start, end)
    now = time.time()

    # 1. In-process cache first
    if key in _mem_cache:
        ts, events = _mem_cache[key]
        if now - ts < _CACHE_TTL_SECONDS:
            return list(events)
        # stale: return but mark
        stale = [{**e, "stale": True} for e in events]
        return stale

    # 2. File cache
    if not _CACHE_FILE.is_file():
        return None
    try:
        with _CACHE_FILE.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("key") != key:
                    continue
                ts = rec.get("compiled_at_epoch", 0)
                events = rec.get("events", [])
                _mem_cache[key] = (ts, events)
                if now - ts < _CACHE_TTL_SECONDS:
                    return list(events)
                return [{**e, "stale": True} for e in events]
    except Exception as e:
        log.debug("cache read failed: %s", e)

    return None


def _write_cache(key: str, events: list[dict]) -> None:
    """Append a fresh compile record. Lightweight: full-file rewrite is OK at our scale."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if _CACHE_FILE.is_file():
            with _CACHE_FILE.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("key") != key:
                            existing.append(rec)
                    except Exception:
                        continue
        record = {
            "key": key,
            "compiled_at_epoch": time.time(),
            "compiled_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "events": events,
        }
        existing.append(record)
        # Trim: keep the most recent 50 entries
        existing = existing[-50:]
        with _CACHE_FILE.open("w") as f:
            for rec in existing:
                f.write(json.dumps(rec) + "\n")
        _mem_cache[key] = (record["compiled_at_epoch"], list(events))
    except Exception as e:
        log.warning("cache write failed: %s", e)


def _schedule_background_refresh(city_id: str, start: date, end: date) -> None:
    """Spawn a background refresh task if one isn't already running."""
    key = _cache_key(city_id, start, end)
    existing = _refresh_tasks.get(key)
    if existing and not existing.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop, caller is sync; skip background refresh

    async def _refresh():
        try:
            events = await _compile_unified_fresh(city_id, start, end)
            _write_cache(key, events)
        except Exception as e:
            log.warning("background refresh failed: %s", e)
        finally:
            _refresh_tasks.pop(key, None)

    _refresh_tasks[key] = loop.create_task(_refresh())


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


async def compile_brain_events(start: date, end: date) -> list[dict]:
    """
    Pull every Brain subsystem with time-anchored items, normalize, sort.
    Each puller is isolated — one failing source does not break compile.
    """
    pullers = [
        ("predictions", _pull_predictions(start, end)),
        ("council", _pull_council(start, end)),
        ("scanner", _pull_scanner(start, end)),
        ("portfolio", _pull_portfolio(start, end)),
        ("intel", _pull_intel(start, end)),
        ("journal", _pull_journal(start, end)),
    ]
    results = await asyncio.gather(*[p[1] for p in pullers], return_exceptions=True)

    flat: list[dict] = []
    for (name, _), res in zip(pullers, results):
        if isinstance(res, Exception):
            log.warning("compiler: source %s failed: %s", name, res)
            continue
        flat.extend(res)

    flat.sort(key=lambda e: (e.get("date", ""), e.get("source", "")))
    return flat


async def _compile_unified_fresh(
    city_id: str,
    start: date,
    end: date,
) -> list[dict]:
    """Fresh compile — Brain + market + local, normalized + sorted."""
    # Pull everything in parallel
    brain_task = compile_brain_events(start, end)

    # market
    async def _market() -> list[dict]:
        try:
            from runtime.calendar.events import get_all_events  # type: ignore

            raw = await get_all_events(start, end)
            out = []
            for ev in raw or []:
                norm = _normalize_market_event(ev)
                if norm:
                    out.append(norm)
            log.info("compiler: market pulled=%d", len(out))
            return out
        except Exception as e:
            log.warning("market events failed: %s", e)
            return []

    # local
    async def _local() -> list[dict]:
        try:
            from runtime.calendar.local_events import get_local_events  # type: ignore

            raw = await get_local_events(city_id, start, end)
            out = []
            for ev in raw or []:
                norm = _normalize_local_event(ev, city_id)
                if norm:
                    out.append(norm)
            log.info("compiler: local pulled=%d (%s)", len(out), city_id)
            return out
        except Exception as e:
            log.warning("local events failed for %s: %s", city_id, e)
            return []

    brain, market, local = await asyncio.gather(
        brain_task, _market(), _local(), return_exceptions=False
    )

    merged = list(brain) + list(market) + list(local)
    # Stable sort: by date then impact priority then source
    impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    merged.sort(
        key=lambda e: (
            e.get("date", ""),
            impact_rank.get(e.get("impact", "low"), 9),
            e.get("source", ""),
        )
    )
    return merged


async def compile_unified_events(
    city_id: str,
    start: date,
    end: date,
) -> list[dict]:
    """
    Public entry — returns cached events if fresh, fetches fresh otherwise.
    Stale cache is returned immediately with `stale: true`, and a background
    refresh is kicked off so the next call gets fresh data.
    """
    key = _cache_key(city_id, start, end)
    cached = await get_cached_compile(city_id, start, end)
    if cached is not None:
        is_stale = any(e.get("stale") for e in cached)
        if is_stale:
            _schedule_background_refresh(city_id, start, end)
        return cached

    # Miss — fetch fresh and persist
    events = await _compile_unified_fresh(city_id, start, end)
    _write_cache(key, events)
    return events


# ─────────────────────────────────────────────────────────────────────
# Quality / dedup / cap filters (post-compile)
# ─────────────────────────────────────────────────────────────────────

# Per-source quality threshold. Score domain mirrors `impact` mapped 0..1.
# A source can be filtered out below its threshold even if it survives global
# `min_quality_score`. Scanner needs a higher bar than journal entries.
_DEFAULT_SOURCE_QUALITY_THRESHOLD = {
    "scanner": 0.75,  # importance_score >= 80 (see _IMPACT_TO_SCORE)
    "intel": 0.40,
    "journal": 0.35,
    "council": 0.45,
    "prediction": 0.40,
    "portfolio": 0.50,
    "market": 0.30,
    "local": 0.20,
    "moon": 0.10,
    "sun": 0.10,
}

# impact -> 0..1 score for filtering (matches importance domain)
_IMPACT_TO_SCORE = {
    "low": 0.25,
    "medium": 0.55,
    "high": 0.80,
    "critical": 0.95,
}


def _event_quality_score(ev: dict) -> float:
    """Map an event to a 0..1 quality score.

    Prefers raw.importance_score (scanner / journal importance) when present,
    falls back to `impact` enum -> score mapping.
    """
    raw = ev.get("raw") or {}
    imp = raw.get("importance_score")
    if isinstance(imp, (int, float)):
        # importance is typically 0..100 in scanner output
        return max(0.0, min(1.0, float(imp) / 100.0))
    j_imp = raw.get("importance")
    if isinstance(j_imp, (int, float)):
        # journal importance is 0..1
        return max(0.0, min(1.0, float(j_imp)))
    return _IMPACT_TO_SCORE.get(ev.get("impact", "low"), 0.25)


def _dedup_scanner_by_ticker_date(events: list[dict]) -> list[dict]:
    """Collapse multiple scanner signals about the same ticker on the same
    date into a single entry (highest-impact wins; merges tickers/entities).
    """
    out: list[dict] = []
    seen: dict[tuple, dict] = {}
    impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for ev in events:
        if ev.get("source") != "scanner":
            out.append(ev)
            continue
        date_str = ev.get("date", "")
        tickers = ev.get("tickers") or []
        key_t = tuple(sorted(tickers)) if tickers else ("__no_ticker__", ev.get("title", "")[:80])
        key = (date_str, key_t)
        prior = seen.get(key)
        if prior is None:
            seen[key] = ev
            out.append(ev)
            continue
        # Keep higher-impact one; merge entities/tickers metadata
        if impact_rank.get(ev.get("impact", "low"), 9) < impact_rank.get(
            prior.get("impact", "low"), 9
        ):
            # current ev wins — replace in-place in out list
            idx = out.index(prior)
            merged_entities = sorted(
                set((prior.get("entities") or []) + (ev.get("entities") or []))
            )
            merged_tickers = sorted(set((prior.get("tickers") or []) + (ev.get("tickers") or [])))
            ev2 = dict(ev)
            ev2["entities"] = merged_entities
            ev2["tickers"] = merged_tickers
            ev2.setdefault("raw", {})["dedup_collapsed"] = ev2["raw"].get("dedup_collapsed", 0) + 1
            out[idx] = ev2
            seen[key] = ev2
        else:
            # prior wins — fold this one's metadata into prior
            prior["entities"] = sorted(
                set((prior.get("entities") or []) + (ev.get("entities") or []))
            )
            prior["tickers"] = sorted(set((prior.get("tickers") or []) + (ev.get("tickers") or [])))
            prior.setdefault("raw", {})["dedup_collapsed"] = (
                prior["raw"].get("dedup_collapsed", 0) + 1
            )
    return out


def _dedup_same_title_24h(events: list[dict]) -> list[dict]:
    """Collapse events sharing the same normalized title on the same date
    into a single entry. The surviving entry gets a `sources` list of all
    contributing source names.
    """
    out: list[dict] = []
    seen: dict[tuple, dict] = {}
    impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for ev in events:
        title_key = (ev.get("title") or "").strip().lower()[:120]
        if not title_key:
            out.append(ev)
            continue
        key = (ev.get("date", ""), title_key)
        prior = seen.get(key)
        if prior is None:
            ev_copy = dict(ev)
            ev_copy.setdefault("sources", [ev.get("source", "")])
            seen[key] = ev_copy
            out.append(ev_copy)
            continue
        # merge — append source, keep higher-impact details
        prior_sources = prior.setdefault("sources", [prior.get("source", "")])
        if ev.get("source") and ev.get("source") not in prior_sources:
            prior_sources.append(ev.get("source"))
        if impact_rank.get(ev.get("impact", "low"), 9) < impact_rank.get(
            prior.get("impact", "low"), 9
        ):
            prior["impact"] = ev.get("impact", prior.get("impact"))
            if ev.get("description") and len(ev.get("description", "")) > len(
                prior.get("description", "")
            ):
                prior["description"] = ev["description"]
    return out


def _cap_scanner_share(events: list[dict], max_share: float = 0.30) -> list[dict]:
    """Enforce that scanner-sourced events make up at most `max_share` of the
    total. Lowest-quality scanner items are dropped first.
    """
    if max_share >= 1.0 or not events:
        return events
    non_scanner = [e for e in events if e.get("source") != "scanner"]
    scanner = [e for e in events if e.get("source") == "scanner"]
    if not scanner:
        return events
    # Allowed scanner count s.t. s / (s + n) <= max_share  =>  s <= n * max/(1-max)
    n = len(non_scanner)
    if max_share <= 0.0:
        allowed = 0
    else:
        allowed = int(n * max_share / max(1e-9, 1.0 - max_share))
    if len(scanner) <= allowed:
        return events
    scanner.sort(key=_event_quality_score, reverse=True)
    kept_scanner = scanner[:allowed]
    out = non_scanner + kept_scanner
    impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(
        key=lambda e: (
            e.get("date", ""),
            impact_rank.get(e.get("impact", "low"), 9),
            e.get("source", ""),
        )
    )
    return out


def _exclude_first_n_days(
    events: list[dict], exclude_days: int, today: Optional[date] = None
) -> list[dict]:
    """Drop events with date < today + exclude_days. Used by 30-day view to
    skip the 7 days already shown in the 7-day tab.
    """
    if exclude_days <= 0:
        return events
    today = today or date.today()
    cutoff = today + timedelta(days=int(exclude_days))
    out = []
    for ev in events:
        d = _coerce_date(ev.get("date"))
        if d is None or d >= cutoff:
            out.append(ev)
    return out


def _source_distribution(events: list[dict]) -> dict:
    dist: dict[str, int] = {}
    for ev in events:
        s = ev.get("source", "unknown") or "unknown"
        dist[s] = dist.get(s, 0) + 1
    return dist


def apply_quality_filters(
    events: list[dict],
    *,
    exclude_window: int = 0,
    scanner_cap: float = 0.30,
    min_quality_score: float = 0.50,
    per_source_quality: Optional[dict] = None,
    today: Optional[date] = None,
) -> dict:
    """Apply the full filter pipeline to a raw compiled-events list.

    Returns a dict with the filtered events plus metrics for observability.
    """
    events_total = len(events)

    # 1. exclude first N days (e.g., 30-day view skipping the 7-day overlap)
    e1 = _exclude_first_n_days(events, exclude_window, today=today)

    # 2. dedup scanner per ticker-per-date
    e2 = _dedup_scanner_by_ticker_date(e1)

    # 3. dedup any same-title within same-date across sources
    e3 = _dedup_same_title_24h(e2)
    events_after_dedup = len(e3)

    # 4. per-source quality threshold + global min_quality_score
    thresholds = dict(_DEFAULT_SOURCE_QUALITY_THRESHOLD)
    if per_source_quality:
        thresholds.update(per_source_quality)

    e4: list[dict] = []
    for ev in e3:
        score = _event_quality_score(ev)
        src = ev.get("source", "")
        # Per-source threshold OVERRIDES global min_quality_score so that
        # curated low-impact sources (e.g., local festivals) aren't filtered
        # out by a global scanner-tuned bar.
        if src in thresholds:
            bar = thresholds[src]
        else:
            bar = min_quality_score
        if score >= bar:
            e4.append(ev)
    events_after_quality_filter = len(e4)

    # 5. cap scanner share of total
    e5 = _cap_scanner_share(e4, max_share=scanner_cap)

    distribution = _source_distribution(e5)
    return {
        "events": e5,
        "metrics": {
            "events_total": events_total,
            "events_after_exclude_window": len(e1),
            "events_after_dedup": events_after_dedup,
            "events_after_quality_filter": events_after_quality_filter,
            "events_after_scanner_cap": len(e5),
            "exclude_window": int(exclude_window),
            "scanner_cap": scanner_cap,
            "min_quality_score": min_quality_score,
        },
        "source_distribution": distribution,
    }


__all__ = [
    "compile_brain_events",
    "compile_unified_events",
    "get_cached_compile",
    "apply_quality_filters",
]
