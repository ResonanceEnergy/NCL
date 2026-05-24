"""
Per-City Event Scanner — "Fun Finder" for the 7 NATRIX cities.

For each city: pulls events, activities, landmarks, festivals, and notable
dates from multiple free sources. Designed to surface things to do — not just
weather and holidays.

Sources (tried in order, graceful fallback on each failure):
    1. Ticketmaster Discovery API   — concerts, sports, arts (existing TM_API_KEY)
    2. Eventbrite                   — HTML scrape, BeautifulSoup optional
    3. Reddit local subreddit       — events flair / search via public JSON
    4. Google Trends                — geo-filtered "events in X" / "festivals X"
    5. News (RSS / NewsAPI)         — local news mentioning events
    6. Curated JSONL                — hand-maintained per-city events
    7. Landmarks bootstrap          — runtime/calendar/data/landmarks.json
    8. Notable dates bootstrap      — runtime/calendar/data/notable_dates.json

City registry lives in `local_events.py:CITIES` (single source of truth).

Cache: `data/calendar/city_events_cache.jsonl` (refreshed by ncl-city-events
loop in scheduler.py, atomic writes).
"""

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
from typing import Optional

import httpx

from .local_events import CITIES, LOCAL_EVENT_CATEGORIES


log = logging.getLogger("ncl.calendar.city_scanner")


# ── Paths (repo-root relative, mirrors cities_pref.py pattern) ──────
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[2]
_DATA_DIR = _REPO_ROOT / "data" / "calendar"
_CURATED_DIR = _DATA_DIR / "curated_events"
_CACHE_PATH = _DATA_DIR / "city_events_cache.jsonl"

_BOOTSTRAP_DIR = _THIS.parent / "data"
_LANDMARKS_PATH = _BOOTSTRAP_DIR / "landmarks.json"
_NOTABLE_DATES_PATH = _BOOTSTRAP_DIR / "notable_dates.json"


# ── Reddit subreddit map per city ────────────────────────────────────
_REDDIT_SUBREDDITS = {
    "edmonton": "Edmonton",
    "calgary": "Calgary",
    "panama_city": "Panama",
    "san_salvador": "ElSalvador",
    "montevideo": "uruguay",
    "asuncion": "Paraguay",
    "oaxaca": "oaxaca",
}

# ── Eventbrite city-slug map ─────────────────────────────────────────
_EVENTBRITE_SLUG = {
    "edmonton": "canada--edmonton",
    "calgary": "canada--calgary",
    "panama_city": "panama--panama-city",
    "san_salvador": "el-salvador--san-salvador",
    "montevideo": "uruguay--montevideo",
    "asuncion": "paraguay--asuncion",
    "oaxaca": "mexico--oaxaca",
}

# ── In-memory cache ──────────────────────────────────────────────────
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600  # 1 hour

# Browser UA pool for Reddit/Eventbrite scraping (bot UAs get 403'd)
_BROWSER_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",  # noqa: E501
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",  # noqa: E501
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = _BROWSER_UAS[_ua_index % len(_BROWSER_UAS)]
    _ua_index += 1
    return ua


# ── Bootstrap loaders ────────────────────────────────────────────────
_landmarks_cache: Optional[dict] = None
_notable_cache: Optional[dict] = None


def _load_landmarks() -> dict:
    global _landmarks_cache
    if _landmarks_cache is not None:
        return _landmarks_cache
    try:
        if _LANDMARKS_PATH.exists():
            with open(_LANDMARKS_PATH) as f:
                _landmarks_cache = json.load(f)
        else:
            log.warning("landmarks.json missing at %s", _LANDMARKS_PATH)
            _landmarks_cache = {}
    except Exception as e:
        log.error("Failed to load landmarks: %s", e)
        _landmarks_cache = {}
    return _landmarks_cache


def _load_notable_dates() -> dict:
    global _notable_cache
    if _notable_cache is not None:
        return _notable_cache
    try:
        if _NOTABLE_DATES_PATH.exists():
            with open(_NOTABLE_DATES_PATH) as f:
                _notable_cache = json.load(f)
        else:
            log.warning("notable_dates.json missing at %s", _NOTABLE_DATES_PATH)
            _notable_cache = {}
    except Exception as e:
        log.error("Failed to load notable_dates: %s", e)
        _notable_cache = {}
    return _notable_cache


def _row_id(city_id: str, source: str, payload: str) -> str:
    h = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"city:{city_id}:{source}:{h}"


def _make_event(
    city_id: str,
    source: str,
    date_str: str,
    title: str,
    description: str = "",
    category: str = "community",
    time_str: Optional[str] = None,
    url: Optional[str] = None,
    venue: Optional[str] = None,
    image_url: Optional[str] = None,
    ticket_required: Optional[bool] = None,
    price_range: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> dict:
    """Normalised event row schema."""
    raw = f"{source}|{date_str}|{title}|{venue or ''}"
    return {
        "id": _row_id(city_id, source, raw),
        "city_id": city_id,
        "date": date_str,
        "time": time_str,
        "title": title,
        "description": description,
        "category": category,
        "source": source,
        "url": url,
        "venue": venue,
        "image_url": image_url,
        "ticket_required": ticket_required,
        "price_range": price_range,
        "tags": tags or [],
    }


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE COLLECTORS
# ═══════════════════════════════════════════════════════════════════════════


async def _from_ticketmaster(city_id: str, start: date, end: date) -> list[dict]:
    """Ticketmaster Discovery API with proximity + classification filter."""
    city = CITIES.get(city_id)
    api_key = os.environ.get("TICKETMASTER_API_KEY") or os.environ.get("TM_API_KEY")
    if not city or not api_key:
        return []

    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            for classification in ("Music", "Sports", "Arts & Theatre", "Family"):
                try:
                    r = await client.get(
                        "https://app.ticketmaster.com/discovery/v2/events.json",
                        params={
                            "apikey": api_key,
                            "latlong": f"{city['lat']},{city['lon']}",
                            "radius": "50",
                            "unit": "km",
                            "classificationName": classification,
                            "startDateTime": f"{start.isoformat()}T00:00:00Z",
                            "endDateTime": f"{end.isoformat()}T23:59:59Z",
                            "size": 15,
                            "sort": "date,asc",
                        },
                    )
                    if r.status_code != 200:
                        log.debug(
                            "[city_scanner:tm] %s %s -> %d", city_id, classification, r.status_code
                        )
                        continue
                    body = r.json()
                    for ev in body.get("_embedded", {}).get("events", []):
                        dates = ev.get("dates", {}).get("start", {})
                        d = dates.get("localDate")
                        t = dates.get("localTime")
                        if not d:
                            continue
                        venue_name = None
                        for v in ev.get("_embedded", {}).get("venues", []):
                            venue_name = v.get("name")
                            break
                        # Best image
                        image = None
                        for img in ev.get("images", []) or []:
                            if img.get("ratio") == "16_9":
                                image = img.get("url")
                                break
                        if not image and ev.get("images"):
                            image = ev["images"][0].get("url")
                        # Price
                        price_range = None
                        pr = ev.get("priceRanges", [])
                        if pr:
                            mn = pr[0].get("min")
                            mx = pr[0].get("max")
                            cur = pr[0].get("currency", "USD")
                            if mn is not None and mx is not None:
                                price_range = f"{cur} {mn:g}-{mx:g}"
                        cat_map = {
                            "Music": "concert",
                            "Sports": "sports",
                            "Arts & Theatre": "cultural",
                            "Family": "community",
                        }
                        rows.append(
                            _make_event(
                                city_id=city_id,
                                source="ticketmaster",
                                date_str=d,
                                title=ev.get("name", "Event")[:200],
                                description=(
                                    ev.get("info") or ev.get("pleaseNote") or venue_name or ""
                                )[:400],
                                category=cat_map.get(classification, "community"),
                                time_str=(t[:5] if t else None),
                                url=ev.get("url"),
                                venue=venue_name,
                                image_url=image,
                                ticket_required=True,
                                price_range=price_range,
                                tags=[classification.lower().split()[0]],
                            )
                        )
                except Exception as e:
                    log.debug("[city_scanner:tm] %s %s exc=%s", city_id, classification, e)
    except Exception as e:
        log.warning("[city_scanner:tm] %s outer: %s", city_id, e)
    return rows


async def _from_eventbrite(city_id: str, start: date, end: date) -> list[dict]:
    """Eventbrite city browse page — defensive HTML scrape."""
    slug = _EVENTBRITE_SLUG.get(city_id)
    if not slug:
        return []
    url = f"https://www.eventbrite.com/d/{slug}/events/"
    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": _next_ua(), "Accept": "text/html"})
            if r.status_code != 200 or not r.text:
                log.debug("[city_scanner:eb] %s -> %d", city_id, r.status_code)
                return []
            html = r.text
    except Exception as e:
        log.debug("[city_scanner:eb] %s fetch failed: %s", city_id, e)
        return []

    parsed: list[dict] = []
    # Prefer BeautifulSoup if available
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        # Eventbrite events appear as JSON-LD payload tags or as eds-event-card-content--styled. Most reliable: JSON-LD <script type="application/ld+json">.  # noqa: E501
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or "{}")
            except Exception as e:
                log.debug("[CITY-SCAN] eventbrite JSON-LD parse swallowed: %s", e)
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("@type") not in ("Event", "MusicEvent", "Festival", "TheaterEvent"):
                    continue
                parsed.append(
                    {
                        "title": it.get("name", "")[:200],
                        "start": it.get("startDate", ""),
                        "url": it.get("url"),
                        "image": it.get("image") if isinstance(it.get("image"), str) else None,
                        "venue": (it.get("location", {}) or {}).get("name")
                        if isinstance(it.get("location"), dict)
                        else None,
                        "description": (it.get("description") or "")[:400],
                    }
                )
    except ImportError:
        # Fallback: regex JSON-LD blocks
        for m in re.finditer(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.+?)</script>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("@type") not in ("Event", "MusicEvent", "Festival", "TheaterEvent"):
                    continue
                parsed.append(
                    {
                        "title": (it.get("name") or "")[:200],
                        "start": it.get("startDate", ""),
                        "url": it.get("url"),
                        "image": it.get("image") if isinstance(it.get("image"), str) else None,
                        "venue": None,
                        "description": (it.get("description") or "")[:400],
                    }
                )

    for p in parsed:
        d_iso = (p.get("start") or "")[:10]
        if not d_iso:
            continue
        try:
            d_obj = date.fromisoformat(d_iso)
        except Exception:
            continue
        if not (start <= d_obj <= end):
            continue
        t_iso = None
        if len(p.get("start", "")) >= 16 and "T" in p["start"]:
            t_iso = p["start"][11:16]
        rows.append(
            _make_event(
                city_id=city_id,
                source="eventbrite",
                date_str=d_iso,
                title=p["title"] or "Eventbrite event",
                description=p.get("description", ""),
                category="community",
                time_str=t_iso,
                url=p.get("url"),
                venue=p.get("venue"),
                image_url=p.get("image"),
                ticket_required=True,
                tags=["eventbrite"],
            )
        )
    return rows


_EVENT_KEYWORDS = re.compile(
    r"\b(event|concert|festival|show|gig|exhibit|exhibition|expo|market|"
    r"parade|fiesta|carnaval|carnival|fair|tournament|race|"
    r"meetup|gathering|opening|premiere|gala)\b",
    re.IGNORECASE,
)


async def _from_reddit(city_id: str, start: date, end: date) -> list[dict]:
    """Scan the city's subreddit for event-flavoured posts (last 7 days)."""
    sub = _REDDIT_SUBREDDITS.get(city_id)
    if not sub:
        return []
    url = f"https://www.reddit.com/r/{sub}/new.json?limit=50"
    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get(url, headers={"User-Agent": _next_ua()})
            if r.status_code != 200:
                log.debug("[city_scanner:reddit] %s/r/%s -> %d", city_id, sub, r.status_code)
                return []
            data = r.json()
    except Exception as e:
        log.debug("[city_scanner:reddit] %s exc=%s", city_id, e)
        return []

    today = date.today()
    for child in (data.get("data", {}) or {}).get("children", []) or []:
        post = child.get("data", {}) or {}
        title = post.get("title", "") or ""
        flair = (post.get("link_flair_text") or "").lower()
        body = post.get("selftext", "") or ""
        permalink = post.get("permalink") or ""
        created = post.get("created_utc") or 0
        # Filter: event-like
        is_event = (
            "event" in flair
            or "concert" in flair
            or "festival" in flair
            or "ann" in flair  # announcement
            or _EVENT_KEYWORDS.search(title)
            or _EVENT_KEYWORDS.search(body[:200])
        )
        if not is_event:
            continue
        # Use today's date as the proxy date — posts in /new are recent
        try:
            ts = datetime.fromtimestamp(created, tz=timezone.utc).date()
        except Exception:
            ts = today
        if ts < start or ts > end:
            # Posts could be discussing past or future events. Stamp with `today`
            # if the post is within the window we care about; else skip.
            if not (start <= today <= end):
                continue
            ts = today
        rows.append(
            _make_event(
                city_id=city_id,
                source="reddit",
                date_str=ts.isoformat(),
                title=title[:200] or "Reddit post",
                description=(body[:400] or post.get("subreddit_name_prefixed", "")),
                category="community",
                url=f"https://reddit.com{permalink}" if permalink else None,
                tags=["reddit", f"r/{sub}", flair] if flair else ["reddit", f"r/{sub}"],
            )
        )
    return rows


async def _from_google_trends(city_id: str, start: date, end: date) -> list[dict]:
    """Best-effort: pytrends geo-trending. Skipped if pytrends unavailable."""
    city = CITIES.get(city_id)
    if not city:
        return []
    try:
        # Async-safe wrapper around the sync pytrends
        loop = asyncio.get_event_loop()

        def _do_query() -> list[dict]:
            try:
                from pytrends.request import TrendReq  # type: ignore
            except ImportError:
                return []
            try:
                pytrend = TrendReq(hl="en-US", tz=0, timeout=(5, 10))
                queries = [
                    f"events in {city['name']}",
                    f"concerts in {city['name']}",
                    f"festivals in {city['name']}",
                ]
                out: list[dict] = []
                for q in queries:
                    try:
                        pytrend.build_payload([q], cat=0, timeframe="now 7-d", geo="")
                        related = pytrend.related_queries()
                        rq = related.get(q, {}) or {}
                        top = rq.get("top")
                        rising = rq.get("rising")
                        for df in (top, rising):
                            if df is None:
                                continue
                            for _, row in df.head(5).iterrows():
                                qstr = row.get("query", "") or ""
                                if not qstr or len(qstr) < 4:
                                    continue
                                out.append(
                                    {
                                        "title": qstr.title(),
                                        "value": int(row.get("value", 0) or 0),
                                    }
                                )
                    except Exception as e:
                        log.debug("[CITY-SCAN] trends keyword row swallowed: %s", e)
                        continue
                return out
            except Exception as e:
                log.debug("[city_scanner:trends] %s err=%s", city_id, e)
                return []

        raw = await loop.run_in_executor(None, _do_query)
    except Exception as e:
        log.debug("[city_scanner:trends] %s outer: %s", city_id, e)
        return []

    rows: list[dict] = []
    today = date.today()
    if not (start <= today <= end):
        return []
    for item in raw[:10]:
        rows.append(
            _make_event(
                city_id=city_id,
                source="trends",
                date_str=today.isoformat(),
                title=f"Trending: {item['title']}",
                description=f"Rising search interest (score {item.get('value', 0)})",
                category="community",
                tags=["trending"],
            )
        )
    return rows


async def _from_news(city_id: str, start: date, end: date) -> list[dict]:
    """Lightweight news search via NewsAPI (if key) — falls through to [].

    EOD 2026-05-22 audit: gated behind NCL_CITY_NEWS_ENABLED (default
    OFF). City scanner runs every ~2min × 7 cities × ~6 categories of
    NewsAPI calls — burned through 100/day free quota in ~30 min, then
    cascading 429 retries stalled the Awarebot news collector and hung
    /context/source/news. Ticketmaster + Eventbrite + RSS already cover
    local events. Set NCL_CITY_NEWS_ENABLED=true once on paid NewsAPI.
    """
    if os.environ.get("NCL_CITY_NEWS_ENABLED", "false").lower() != "true":
        return []
    city = CITIES.get(city_id)
    if not city:
        return []
    api_key = os.environ.get("NEWSAPI_KEY") or os.environ.get("NEWS_API_KEY")
    if not api_key:
        return []
    rows: list[dict] = []
    query = f'"{city["name"]}" AND (event OR concert OR festival OR opening OR exhibition)'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "language": "en",
                    "pageSize": 10,
                    "sortBy": "publishedAt",
                    "apiKey": api_key,
                },
            )
            if r.status_code != 200:
                log.debug("[city_scanner:news] %s -> %d", city_id, r.status_code)
                return []
            body = r.json()
    except Exception as e:
        log.debug("[city_scanner:news] %s exc=%s", city_id, e)
        return []

    for art in body.get("articles", [])[:10]:
        published = (art.get("publishedAt") or "")[:10]
        if not published:
            continue
        try:
            d_obj = date.fromisoformat(published)
        except Exception:
            continue
        if not (start <= d_obj <= end):
            continue
        rows.append(
            _make_event(
                city_id=city_id,
                source="news",
                date_str=published,
                title=(art.get("title") or "News")[:200],
                description=(art.get("description") or "")[:400],
                category="community",
                url=art.get("url"),
                image_url=art.get("urlToImage"),
                tags=["news", art.get("source", {}).get("name", "")[:50]],
            )
        )
    return rows


def _from_curated_jsonl(city_id: str, start: date, end: date) -> list[dict]:
    """Read curated events from `data/calendar/curated_events/{city_id}.jsonl`.

    Two flavours supported:
      - Concrete date events: {"date": "YYYY-MM-DD", ...}
      - Recurring events:     {"date": "recurring:<weekday|daily>", "recurrence": "weekly:<day>"}
    """
    path = _CURATED_DIR / f"{city_id}.jsonl"
    rows: list[dict] = []
    if not path.exists():
        return rows
    try:
        with open(path) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except Exception as e:
        log.warning("curated read %s failed: %s", path, e)
        return rows

    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    month_map = {  # noqa: F841
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    for line in lines:
        try:
            raw = json.loads(line)
        except Exception:
            continue
        date_field = (raw.get("date") or "").strip()
        title = raw.get("title", "Untitled")
        season = raw.get("season")  # optional ["jun","jul","aug"]
        recurrence = (raw.get("recurrence") or "").lower()

        # Concrete date
        if date_field and not date_field.startswith("recurring"):
            try:
                d_obj = date.fromisoformat(date_field)
            except Exception:
                continue
            if start <= d_obj <= end:
                rows.append(
                    _make_event(
                        city_id=city_id,
                        source="curated",
                        date_str=date_field,
                        title=title,
                        description=raw.get("description", ""),
                        category=raw.get("category", "community"),
                        time_str=raw.get("time"),
                        url=raw.get("url"),
                        venue=raw.get("venue"),
                        tags=raw.get("tags", []),
                    )
                )
            continue

        # Recurring (expand into the window)
        target_weekday = None
        is_daily = False
        if date_field.startswith("recurring:"):
            kind = date_field.split(":", 1)[1].strip()
            if kind == "daily":
                is_daily = True
            elif kind in weekday_map:
                target_weekday = weekday_map[kind]
        elif recurrence.startswith("weekly:"):
            day_label = recurrence.split(":", 1)[1].strip().split("-")[0]
            target_weekday = weekday_map.get(day_label)

        if not is_daily and target_weekday is None:
            continue

        # Expand
        cur = start
        while cur <= end:
            in_season = True
            if season:
                in_season = cur.strftime("%b").lower() in [s.lower() for s in season]
            in_day = is_daily or (cur.weekday() == target_weekday)
            if in_day and in_season:
                rows.append(
                    _make_event(
                        city_id=city_id,
                        source="curated",
                        date_str=cur.isoformat(),
                        title=title,
                        description=raw.get("description", ""),
                        category=raw.get("category", "community"),
                        time_str=raw.get("time"),
                        venue=raw.get("venue"),
                        tags=raw.get("tags", []) + ["recurring"],
                    )
                )
            cur = cur + timedelta(days=1)
    return rows


def _from_notable_dates(city_id: str, start: date, end: date) -> list[dict]:
    """Annual recurring notable dates from notable_dates.json."""
    notable = _load_notable_dates()
    items = notable.get(city_id, [])
    rows: list[dict] = []
    for item in items:
        for year in range(start.year, end.year + 1):
            try:
                d_obj = date(year, item["month"], item["day"])
            except (KeyError, ValueError):
                continue
            if not (start <= d_obj <= end):
                continue
            rows.append(
                _make_event(
                    city_id=city_id,
                    source="notable_date",
                    date_str=d_obj.isoformat(),
                    title=item.get("title", "Notable date"),
                    description=item.get("description", ""),
                    category=item.get("category", "notable_date"),
                    tags=item.get("tags", []) + ["annual"],
                )
            )
            # If an end_month/end_day is set, fill the range
            end_m, end_d = item.get("end_month"), item.get("end_day")
            if end_m and end_d:
                try:
                    end_obj = date(year, end_m, end_d)
                except ValueError:
                    continue
                cur = d_obj + timedelta(days=1)
                while cur <= end_obj and cur <= end:
                    if cur >= start:
                        rows.append(
                            _make_event(
                                city_id=city_id,
                                source="notable_date",
                                date_str=cur.isoformat(),
                                title=f"{item.get('title')} (ongoing)",
                                description=item.get("description", ""),
                                category=item.get("category", "notable_date"),
                                tags=item.get("tags", []) + ["annual", "ongoing"],
                            )
                        )
                    cur = cur + timedelta(days=1)
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════


class CityEventScanner:
    """Per-city event aggregator. Stateless — caches via module-level _cache."""

    def __init__(self, async_writer=None):
        """async_writer is an optional `runtime.memory.async_writer.AsyncMemoryWriter`.

        When supplied, scan_city() will enqueue each event into MemoryStore.
        """
        self.async_writer = async_writer

    # ────────────────────────────────────────────────────────────────
    async def scan_city(
        self,
        city_id: str,
        lookback_days: int = 0,
        lookahead_days: int = 30,
        bypass_cache: bool = False,
    ) -> dict:
        """Run all sources for a city in parallel, return merged payload.

        Returns:
            {
                "city_id": str,
                "city_name": str,
                "scanned_at": iso8601,
                "events": [...],
                "landmarks": [...],
                "notable_dates": [...],
                "fun_finder": {
                    "today": [...],
                    "this_week": [...],
                    "this_month": [...],
                },
                "sources_used": [str],
                "errors": [str],
            }
        """
        if city_id not in CITIES:
            return {
                "city_id": city_id,
                "error": f"unknown city: {city_id}",
                "events": [],
            }
        cache_key = f"{city_id}:{lookback_days}:{lookahead_days}"
        if not bypass_cache and cache_key in _cache:
            ts, data = _cache[cache_key]
            if time.time() - ts < _CACHE_TTL:
                return data

        today = date.today()
        start = today - timedelta(days=max(0, lookback_days))
        end = today + timedelta(days=max(1, lookahead_days))

        sources_used: list[str] = []
        errors: list[str] = []

        async def _safe(name: str, coro):
            try:
                r = await coro
                if r:
                    sources_used.append(name)
                return r or []
            except Exception as e:
                errors.append(f"{name}: {e!s}"[:200])
                log.warning("[city_scanner] %s/%s failed: %s", city_id, name, e)
                return []

        # Parallel: I/O bound async sources
        tm_t = _safe("ticketmaster", _from_ticketmaster(city_id, start, end))
        eb_t = _safe("eventbrite", _from_eventbrite(city_id, start, end))
        rd_t = _safe("reddit", _from_reddit(city_id, start, end))
        tr_t = _safe("trends", _from_google_trends(city_id, start, end))
        nw_t = _safe("news", _from_news(city_id, start, end))

        tm, eb, rd, tr, nw = await asyncio.gather(tm_t, eb_t, rd_t, tr_t, nw_t)

        # Sync sources
        cur = _from_curated_jsonl(city_id, start, end)
        if cur:
            sources_used.append("curated")
        notable = _from_notable_dates(city_id, start, end)
        if notable:
            sources_used.append("notable_date")

        events = []
        for batch in (tm, eb, rd, tr, nw, cur, notable):
            events.extend(batch)

        # Dedup by (date, lower(title)) — different sources often report same event
        seen: set[tuple[str, str]] = set()
        deduped: list[dict] = []
        for ev in events:
            key = (ev["date"], (ev["title"] or "")[:80].lower().strip())
            if key in seen:
                continue
            seen.add(key)
            # Decorate with category metadata
            cat = ev.get("category", "community")
            meta = LOCAL_EVENT_CATEGORIES.get(cat, LOCAL_EVENT_CATEGORIES["local"])
            ev["category_label"] = meta["label"]
            ev["category_color"] = meta["color"]
            ev["category_icon"] = meta["icon"]
            ev["priority"] = meta["priority"]
            deduped.append(ev)

        deduped.sort(key=lambda e: (e["date"], -e.get("priority", 0), e["title"]))

        # Fun-finder grouping
        today_iso = today.isoformat()
        week_end_iso = (today + timedelta(days=7)).isoformat()
        month_end_iso = (today + timedelta(days=30)).isoformat()
        fun_finder = {
            "today": [e for e in deduped if e["date"] == today_iso],
            "this_week": [e for e in deduped if today_iso < e["date"] <= week_end_iso],
            "this_month": [e for e in deduped if week_end_iso < e["date"] <= month_end_iso],
        }

        landmarks = await self.get_landmarks(city_id)
        notable_dates_full = await self.get_notable_dates(city_id, lookahead_days=90)

        city = CITIES[city_id]
        payload = {
            "city_id": city_id,
            "city_name": city["name"],
            "country": city["country"],
            "timezone": city["timezone"],
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "events": deduped,
            "landmarks": landmarks,
            "notable_dates": notable_dates_full,
            "fun_finder": fun_finder,
            "stats": {
                "total_events": len(deduped),
                "today_count": len(fun_finder["today"]),
                "this_week_count": len(fun_finder["this_week"]),
                "this_month_count": len(fun_finder["this_month"]),
                "landmark_count": len(landmarks),
            },
            "sources_used": sources_used,
            "errors": errors,
        }

        _cache[cache_key] = (time.time(), payload)

        # Fire-and-forget memory writes per event (when async_writer wired)
        if self.async_writer is not None and deduped:
            await self._enqueue_to_memory(city_id, deduped)

        return payload

    # ────────────────────────────────────────────────────────────────
    async def get_landmarks(self, city_id: str) -> list[dict]:
        """Static landmarks for a city, enriched with category meta."""
        if city_id not in CITIES:
            return []
        all_lm = _load_landmarks()
        raw = all_lm.get(city_id, [])
        out: list[dict] = []
        for lm in raw:
            row = {
                **lm,
                "city_id": city_id,
                "source": "curated",
                "category": "landmark",
            }
            meta = LOCAL_EVENT_CATEGORIES.get("local", LOCAL_EVENT_CATEGORIES["local"])
            # landmarks borrow the 'local' icon if no explicit category mapped
            row["category_color"] = meta["color"]
            row["category_icon"] = "mappin.and.ellipse"
            out.append(row)
        return out

    # ────────────────────────────────────────────────────────────────
    async def get_notable_dates(
        self,
        city_id: str,
        lookahead_days: int = 90,
    ) -> list[dict]:
        """Expanded notable dates for the city in the upcoming window."""
        if city_id not in CITIES:
            return []
        today = date.today()
        end = today + timedelta(days=lookahead_days)
        return _from_notable_dates(city_id, today, end)

    # ────────────────────────────────────────────────────────────────
    async def _enqueue_to_memory(self, city_id: str, events: list[dict]) -> None:
        """Fire-and-forget enqueue into MemoryStore via async_writer.

        Importance heuristic:
            festival/notable_date  → 65
            concert/sports         → 55
            cultural               → 55
            community/food/outdoor → 45
        Proximity boost: +10 if within 7 days, +5 if within 30 days.
        """
        try:
            from ..memory.async_writer import WriteRequest
        except Exception:
            return

        today = date.today()
        proximity_boost = lambda d_iso: (  # noqa: E731
            10
            if d_iso <= (today + timedelta(days=7)).isoformat()
            else 5
            if d_iso <= (today + timedelta(days=30)).isoformat()
            else 0
        )
        base = {
            "festival": 65,
            "notable_date": 65,
            "concert": 55,
            "sports": 55,
            "cultural": 55,
            "community": 45,
            "food": 45,
            "outdoor": 45,
            "landmark": 40,
        }
        for ev in events:
            cat = ev.get("category", "community")
            imp = base.get(cat, 40) + proximity_boost(ev["date"])
            imp = min(imp, 90)
            content = (
                f"{ev['date']} {ev.get('time') or ''} — {ev['title']} "
                f"({city_id}, {ev.get('source', 'city_events')}) "
                f"{ev.get('description', '')[:200]}"
            ).strip()
            try:
                await self.async_writer.enqueue(
                    WriteRequest(
                        content=content,
                        source=f"awarebot:city_events:{city_id}",
                        importance=float(imp),
                        memory_type="episodic",
                        tags=["city_events", city_id, cat] + (ev.get("tags") or [])[:5],
                        metadata={
                            "city_id": city_id,
                            "event_id": ev.get("id"),
                            "date": ev["date"],
                            "category": cat,
                            "source": ev.get("source"),
                            "url": ev.get("url"),
                            "authority_tier": "scanner",
                        },
                    )
                )
            except Exception as e:
                log.debug("[city_scanner] enqueue failed for %s: %s", ev.get("id"), e)


# ═══════════════════════════════════════════════════════════════════════════
# CACHE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════


def write_cache_atomic(payload: dict, path: Path = _CACHE_PATH) -> bool:
    """Append-only JSONL cache, written atomically."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        # We append, but use the tmp-then-replace pattern to avoid torn writes
        # on the *last* line (most likely to be read by iOS instant-read).
        existing = ""
        if path.exists():
            try:
                with open(path, "r") as f:
                    existing = f.read()
            except Exception:
                existing = ""
        with open(tmp, "w") as f:
            f.write(existing + line)
        os.replace(tmp, path)
        return True
    except Exception as e:
        log.error("write_cache_atomic failed: %s", e)
        return False


def read_cache_latest(city_id: str, path: Path = _CACHE_PATH) -> Optional[dict]:
    """Return the most recent cached payload for a city (or None)."""
    if not path.exists():
        return None
    try:
        latest: Optional[dict] = None
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("city_id") == city_id:
                    latest = rec
        return latest
    except Exception as e:
        log.warning("read_cache_latest failed: %s", e)
        return None


# ── Module-level singleton convenience ──────────────────────────────
_scanner_singleton: Optional[CityEventScanner] = None


def get_city_scanner(async_writer=None) -> CityEventScanner:
    """Return the singleton scanner. async_writer wired on first call only."""
    global _scanner_singleton
    if _scanner_singleton is None:
        _scanner_singleton = CityEventScanner(async_writer=async_writer)
    elif async_writer is not None and _scanner_singleton.async_writer is None:
        _scanner_singleton.async_writer = async_writer
    return _scanner_singleton
