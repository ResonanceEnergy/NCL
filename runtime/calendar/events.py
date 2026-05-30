"""
Market events calendar — economic releases, options expiry, FOMC, and custom events.

Combines hardcoded deterministic events (options expiry, FOMC) with
dynamic data from Finnhub economic calendar API.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx


log = logging.getLogger("ncl.calendar.events")

# ── Cache for API results ─────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}  # key -> (timestamp, data)
CACHE_TTL = 3600 * 4  # 4 hours

# ── Event categories ──────────────────────────────────────────────────

EVENT_CATEGORIES = {
    "fomc": {"label": "FOMC", "color": "#E94560", "priority": 5, "icon": "building.columns"},
    "cpi": {"label": "CPI", "color": "#FF6B6B", "priority": 4, "icon": "chart.line.uptrend.xyaxis"},
    "nfp": {"label": "Jobs Report", "color": "#FFA07A", "priority": 4, "icon": "person.3"},
    "gdp": {"label": "GDP", "color": "#FFD700", "priority": 3, "icon": "chart.bar"},
    "ppi": {"label": "PPI", "color": "#FFA500", "priority": 3, "icon": "shippingbox"},
    "earnings": {
        "label": "Earnings",
        "color": "#4ECDC4",
        "priority": 3,
        "icon": "dollarsign.circle",
    },
    "opex": {
        "label": "Options Expiry",
        "color": "#9B59B6",
        "priority": 4,
        "icon": "clock.badge.exclamationmark",
    },
    "vix_expiry": {
        "label": "VIX Expiry",
        "color": "#E74C3C",
        "priority": 3,
        "icon": "waveform.path.ecg",
    },
    "futures_roll": {
        "label": "Futures Roll",
        "color": "#3498DB",
        "priority": 2,
        "icon": "arrow.triangle.2.circlepath",
    },
    "fed_speech": {"label": "Fed Speech", "color": "#E67E22", "priority": 2, "icon": "mic"},
    "economic": {"label": "Economic", "color": "#95A5A6", "priority": 2, "icon": "newspaper"},
    "custom": {"label": "Custom", "color": "#1ABC9C", "priority": 1, "icon": "star"},
}


# ── Deterministic events (hardcoded rules) ────────────────────────────


def _third_friday(year: int, month: int) -> date:
    """Monthly options expiry — 3rd Friday of the month."""
    d = date(year, month, 1)
    # Find first Friday
    while d.weekday() != 4:  # Friday
        d += timedelta(days=1)
    # Add 2 weeks for 3rd Friday
    return d + timedelta(weeks=2)


# FOMC meeting dates (2026 schedule — update annually)
FOMC_DATES_2026 = [
    # (start, end, decision_day)
    ("2026-01-27", "2026-01-28", "2026-01-28"),
    ("2026-03-17", "2026-03-18", "2026-03-18"),
    ("2026-05-05", "2026-05-06", "2026-05-06"),
    ("2026-06-16", "2026-06-17", "2026-06-17"),
    ("2026-07-28", "2026-07-29", "2026-07-29"),
    ("2026-09-15", "2026-09-16", "2026-09-16"),
    ("2026-10-27", "2026-10-28", "2026-10-28"),
    ("2026-12-15", "2026-12-16", "2026-12-16"),
]

# Quarterly futures roll months (E-mini S&P, NQ, etc.)
FUTURES_ROLL_MONTHS = [3, 6, 9, 12]


def get_deterministic_events(start: date, end: date) -> list[dict]:
    """
    Generate deterministic market events (options expiry, FOMC, futures roll).
    These don't require API calls — they follow fixed rules.
    """
    events = []
    current = start

    while current <= end:
        y, m = current.year, current.month

        # Monthly options expiry (3rd Friday)
        opex = _third_friday(y, m)
        if start <= opex <= end:
            events.append(
                {
                    "date": opex.isoformat(),
                    "title": "Monthly Options Expiry",
                    "category": "opex",
                    "description": "Monthly equity options expire. Expect increased volume and potential pin action.",  # noqa: E501
                    "impact": "high",
                    "all_day": True,
                }
            )

        # Quad witching (Mar, Jun, Sep, Dec 3rd Friday)
        if m in [3, 6, 9, 12] and start <= opex <= end:
            events[-1]["title"] = "Quad Witching"
            events[-1]["description"] = (
                "Stock options, index options, index futures, and single stock futures "
                "all expire. Expect extreme volume and volatility."
            )
            events[-1]["impact"] = "critical"

        # FOMC meetings
        for fomc_start, fomc_end, decision in FOMC_DATES_2026:
            fs = date.fromisoformat(fomc_start)
            fe = date.fromisoformat(fomc_end)  # noqa: F841
            fd = date.fromisoformat(decision)

            if start <= fs <= end:
                events.append(
                    {
                        "date": fs.isoformat(),
                        "title": "FOMC Meeting Begins",
                        "category": "fomc",
                        "description": "Federal Open Market Committee meeting starts.",
                        "impact": "high" if fs == fd else "medium",
                        "all_day": True,
                    }
                )
            if start <= fd <= end and fd != fs:
                events.append(
                    {
                        "date": fd.isoformat(),
                        "title": "FOMC Decision Day",
                        "category": "fomc",
                        "description": "Rate decision and press conference at 2:00 PM ET.",
                        "impact": "critical",
                        "all_day": False,
                        "time": "14:00 ET",
                    }
                )

        # Futures roll (2nd Thursday before 3rd Friday of roll months)
        if m in FUTURES_ROLL_MONTHS:
            roll_date = opex - timedelta(days=8)  # ~Thursday before expiry week
            if start <= roll_date <= end:
                events.append(
                    {
                        "date": roll_date.isoformat(),
                        "title": "Futures Roll Period Begins",
                        "category": "futures_roll",
                        "description": f"Q{(m-1)//3+1} futures contracts begin rolling to next quarter.",  # noqa: E501
                        "impact": "medium",
                        "all_day": True,
                    }
                )

        # VIX expiry (usually Wednesday 30 days before next month's opex)
        if m < 12:
            next_opex = _third_friday(y, m + 1)
        else:
            next_opex = _third_friday(y + 1, 1)
        vix_exp = next_opex - timedelta(days=30)
        # VIX settles on Wednesday
        while vix_exp.weekday() != 2:
            vix_exp += timedelta(days=1)
        if start <= vix_exp <= end:
            events.append(
                {
                    "date": vix_exp.isoformat(),
                    "title": "VIX Expiry",
                    "category": "vix_expiry",
                    "description": "VIX futures and options settlement. Watch for volatility crush or spike.",  # noqa: E501
                    "impact": "medium",
                    "all_day": True,
                }
            )

        # Move to next month
        if m == 12:
            current = date(y + 1, 1, 1)
        else:
            current = date(y, m + 1, 1)

    # Deduplicate by (date, title)
    seen = set()
    unique = []
    for e in events:
        key = (e["date"], e["title"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return sorted(unique, key=lambda e: e["date"])


# ── Finnhub economic calendar ─────────────────────────────────────────


async def get_economic_events(start: date, end: date) -> list[dict]:
    """
    Fetch economic calendar from Finnhub API.
    Returns CPI, PPI, GDP, jobs data, Fed speeches, etc.
    """
    cache_key = f"finnhub_{start}_{end}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data

    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        log.debug("No FINNHUB_API_KEY — skipping economic calendar")
        return []

    events = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "token": api_key,
                },
            )
            if resp.status_code != 200:
                log.warning("Finnhub calendar API returned %d", resp.status_code)
                return []

            data = resp.json()
            for item in data.get("economicCalendar", []):
                # Map Finnhub event to our format
                event_name = item.get("event", "")
                category = _classify_economic_event(event_name)
                impact_map = {"low": "low", "medium": "medium", "high": "high"}
                impact = impact_map.get(item.get("impact", ""), "low")

                events.append(
                    {
                        "date": item.get("date", ""),
                        "title": event_name,
                        "category": category,
                        "description": _build_economic_description(item),
                        "impact": impact,
                        "all_day": False,
                        "time": item.get("time", ""),
                        "country": item.get("country", "US"),
                        "previous": item.get("prev"),
                        "estimate": item.get("estimate"),
                        "actual": item.get("actual"),
                    }
                )

    except Exception as e:
        log.error("Finnhub economic calendar error: %s", e)

    _cache[cache_key] = (time.time(), events)
    return events


def _classify_economic_event(name: str) -> str:
    """Classify a Finnhub event name into our categories."""
    name_lower = name.lower()
    if "cpi" in name_lower or "consumer price" in name_lower:
        return "cpi"
    elif "nonfarm" in name_lower or "payroll" in name_lower or "employment" in name_lower:
        return "nfp"
    elif "gdp" in name_lower or "gross domestic" in name_lower:
        return "gdp"
    elif "ppi" in name_lower or "producer price" in name_lower:
        return "ppi"
    elif "fomc" in name_lower or "federal reserve" in name_lower or "fed" in name_lower:
        if "speech" in name_lower or "speaks" in name_lower:
            return "fed_speech"
        return "fomc"
    else:
        return "economic"


def _build_economic_description(item: dict) -> str:
    """Build a human-readable description from Finnhub data."""
    parts = [item.get("event", "")]
    if item.get("estimate") is not None:
        parts.append(f"Estimate: {item['estimate']}")
    if item.get("prev") is not None:
        parts.append(f"Previous: {item['prev']}")
    if item.get("actual") is not None:
        parts.append(f"Actual: {item['actual']}")
    return " | ".join(parts)


# ── Wave 14AH — Federal Reserve RSS (free, self-updating) ────────────


async def get_fed_rss_events(start: date, end: date) -> list[dict]:
    """Federal Reserve speeches + press releases inside the date window.

    Pulls live feeds; ranks press-release titles containing 'FOMC' as
    fomc category (priority 5), all other press releases as economic,
    speeches as fed_speech.
    """
    from email.utils import parsedate_to_datetime

    from ..intelligence import free_sources as _fs

    events: list[dict] = []
    speeches = await _fs.fetch_fed_speeches(limit=30)
    press = await _fs.fetch_fed_press_releases(limit=40)

    def _parse(pub: str) -> Optional[date]:
        if not pub:
            return None
        try:
            return parsedate_to_datetime(pub).date()
        except Exception:
            try:
                return date.fromisoformat(pub[:10])
            except Exception:
                return None

    for item in speeches:
        d = _parse(item.get("published", ""))
        if d is None or not (start <= d <= end):
            continue
        events.append(
            {
                "date": d.isoformat(),
                "title": item["title"][:140],
                "category": "fed_speech",
                "description": (item.get("description") or "")[:200] or "Federal Reserve speech",
                "impact": "low",
                "url": item.get("url", ""),
                "source": "fed_rss",
                "all_day": True,
            }
        )

    for item in press:
        d = _parse(item.get("published", ""))
        if d is None or not (start <= d <= end):
            continue
        title_lc = item["title"].lower()
        is_fomc = "fomc" in title_lc or "federal open market committee" in title_lc
        events.append(
            {
                "date": d.isoformat(),
                "title": item["title"][:140],
                "category": "fomc" if is_fomc else "economic",
                "description": (item.get("description") or "")[:200] or "Federal Reserve press release",
                "impact": "high" if is_fomc else "medium",
                "url": item.get("url", ""),
                "source": "fed_rss",
                "all_day": True,
            }
        )
    return events


# ── Combined calendar ─────────────────────────────────────────────────


async def get_all_events(
    start: date,
    end: date,
    include_economic: bool = True,
) -> list[dict]:
    """
    Get all events for a date range — deterministic + economic + custom.
    Enriches each event with category metadata.
    """
    events = get_deterministic_events(start, end)

    if include_economic:
        econ = await get_economic_events(start, end)
        events.extend(econ)

    # Wave 14AH (2026-05-30) — Federal Reserve RSS speeches + press
    # releases. Free, no key, self-updating. Replaces the maintenance
    # burden of the hardcoded FOMC_DATES_2026 list with a live feed.
    try:
        fed_events = await get_fed_rss_events(start, end)
        events.extend(fed_events)
    except Exception as e:
        log.debug("[calendar] fed-rss events fetch failed: %s", e)

    # Load custom events from disk
    custom = _load_custom_events(start, end)
    events.extend(custom)

    # Enrich with category metadata
    for event in events:
        cat = event.get("category", "custom")
        meta = EVENT_CATEGORIES.get(cat, EVENT_CATEGORIES["custom"])
        event["category_label"] = meta["label"]
        event["category_color"] = meta["color"]
        event["category_icon"] = meta["icon"]
        event["priority"] = meta["priority"]

    # Sort by date, then priority (high first)
    events.sort(key=lambda e: (e["date"], -e.get("priority", 0)))

    return events


# ─── Wave 14AQ (2026-05-30) — Financial vs Infotainment split ─────────


# Categories that count as FINANCIAL — markets, macro releases, Fed,
# earnings, expiries, futures roll. Goes to the Portfolio-adjacent
# financial calendar stream.
_FINANCIAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "fomc",
        "cpi",
        "nfp",
        "gdp",
        "ppi",
        "earnings",
        "opex",
        "vix_expiry",
        "futures_roll",
        "fed_speech",
        "economic",
    }
)


def categorize_event_stream(event: dict) -> str:
    """Return 'financial' or 'infotainment' for an enriched event.

    Used by the iOS Calendar tab to render the two streams as
    separate sections per NATRIX directive 2026-05-30: "separate
    financial from infotainment" — the financial calendar serves
    PORTFOLIO decisions while infotainment serves life-schedule
    awareness.
    """
    cat = (event.get("category") or "").lower()
    return "financial" if cat in _FINANCIAL_CATEGORIES else "infotainment"


async def get_all_events_split(
    start: date,
    end: date,
    include_economic: bool = True,
    include_local: bool = True,
    city_id: str = "edmonton",
) -> dict:
    """Wave 14AQ — return events partitioned into financial + infotainment.

    Combines the financial-leaning stream (get_all_events: FOMC, CPI,
    earnings, expiries, fed speeches) with the life-schedule stream
    (local_events: holidays, weather, ticketmaster, city open-data).

    Returns:
        {
            "financial":    [...],   # sorted by date then priority
            "infotainment": [...],
            "counts":       {financial: int, infotainment: int},
            "window":       {start, end, days, city_id}
        }
    """
    # Financial-leaning events from this module
    base_events = await get_all_events(start, end, include_economic=include_economic)

    # Infotainment from local_events.py — holidays + weather + tickets +
    # city open-data + curated.
    local_events: list[dict] = []
    if include_local:
        try:
            from .local_events import get_local_events  # local to avoid cycle

            local_events = await get_local_events(city_id, start, end)
        except Exception as e:
            log.debug("[calendar:split] get_local_events(%s) failed: %s", city_id, e)
            local_events = []

    financial: list[dict] = []
    infotainment: list[dict] = []
    for ev in base_events:
        if categorize_event_stream(ev) == "financial":
            financial.append(ev)
        else:
            infotainment.append(ev)
    for ev in local_events:
        # Local events are infotainment by definition.
        if categorize_event_stream(ev) == "financial":
            financial.append(ev)
        else:
            infotainment.append(ev)

    # Sort both streams by date then priority desc
    financial.sort(key=lambda e: (e["date"], -e.get("priority", 0)))
    infotainment.sort(key=lambda e: (e["date"], -e.get("priority", 0)))

    return {
        "financial": financial,
        "infotainment": infotainment,
        "counts": {
            "financial": len(financial),
            "infotainment": len(infotainment),
        },
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days,
            "city_id": city_id,
        },
    }


# ── Custom events persistence ─────────────────────────────────────────

_CUSTOM_EVENTS_PATH = os.path.expanduser("~/NCL/data/calendar/custom_events.jsonl")


def _load_custom_events(start: date, end: date) -> list[dict]:
    """Load user-defined custom events from JSONL file."""
    if not os.path.exists(_CUSTOM_EVENTS_PATH):
        return []

    events = []
    try:
        with open(_CUSTOM_EVENTS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                event_date = date.fromisoformat(event.get("date", ""))
                if start <= event_date <= end:
                    event["category"] = event.get("category", "custom")
                    events.append(event)
    except Exception as e:
        log.error("Error loading custom events: %s", e)

    return events


def add_custom_event(event: dict) -> dict:
    """Add a custom event to the JSONL store."""
    os.makedirs(os.path.dirname(_CUSTOM_EVENTS_PATH), exist_ok=True)

    event.setdefault("category", "custom")
    event.setdefault("impact", "low")
    event.setdefault("all_day", True)
    event["created_at"] = datetime.now(timezone.utc).isoformat()

    with open(_CUSTOM_EVENTS_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")

    log.info("Custom event added: %s on %s", event.get("title"), event.get("date"))
    return event
