"""
Local events per city — cultural, business, sports, holidays, weather, community.

Aggregates events from multiple free APIs:
  - Calendarific (public holidays)
  - Open-Meteo (weather forecasts — notable conditions)
  - Ticketmaster Discovery API (concerts, sports, shows)
  - Custom curated events from JSONL

Cities: Edmonton, Calgary, Panama City, San Salvador, Montevideo, Asuncion, Oaxaca
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

log = logging.getLogger("ncl.calendar.local_events")

# ── Cache ────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 3600 * 2  # 2 hours

# ── City Configuration ───────────────────────────────────────────────

CITIES = {
    "edmonton": {
        "name": "Edmonton",
        "country": "CA",
        "country_name": "Canada",
        "lat": 53.5461,
        "lon": -113.4937,
        "timezone": "America/Edmonton",
        "icon": "snowflake",
        "color": "#4FC3F7",
    },
    "calgary": {
        "name": "Calgary",
        "country": "CA",
        "country_name": "Canada",
        "lat": 51.0447,
        "lon": -114.0719,
        "timezone": "America/Edmonton",
        "icon": "mountain.2",
        "color": "#81C784",
    },
    "panama_city": {
        "name": "Panama City",
        "country": "PA",
        "country_name": "Panama",
        "lat": 8.9824,
        "lon": -79.5199,
        "timezone": "America/Panama",
        "icon": "building.2",
        "color": "#FFD54F",
    },
    "san_salvador": {
        "name": "San Salvador",
        "country": "SV",
        "country_name": "El Salvador",
        "lat": 13.6929,
        "lon": -89.2182,
        "timezone": "America/El_Salvador",
        "icon": "sun.max",
        "color": "#FF8A65",
    },
    "montevideo": {
        "name": "Montevideo",
        "country": "UY",
        "country_name": "Uruguay",
        "lat": -34.9011,
        "lon": -56.1645,
        "timezone": "America/Montevideo",
        "icon": "water.waves",
        "color": "#7986CB",
    },
    "asuncion": {
        "name": "Asuncion",
        "country": "PY",
        "country_name": "Paraguay",
        "lat": -25.2637,
        "lon": -57.5759,
        "timezone": "America/Asuncion",
        "icon": "leaf",
        "color": "#AED581",
    },
    "oaxaca": {
        "name": "Oaxaca",
        "country": "MX",
        "country_name": "Mexico",
        "lat": 17.0732,
        "lon": -96.7266,
        "timezone": "America/Mexico_City",
        "icon": "paintpalette",
        "color": "#CE93D8",
    },
}

# ── Local event categories ───────────────────────────────────────────

LOCAL_EVENT_CATEGORIES = {
    "holiday": {"label": "Holiday", "color": "#E94560", "icon": "gift", "priority": 5},
    "weather": {"label": "Weather", "color": "#4FC3F7", "icon": "cloud.sun", "priority": 4},
    "sports": {"label": "Sports", "color": "#81C784", "icon": "sportscourt", "priority": 3},
    "concert": {"label": "Concert", "color": "#CE93D8", "icon": "music.note", "priority": 3},
    "festival": {"label": "Festival", "color": "#FFD54F", "icon": "party.popper", "priority": 4},
    "community": {"label": "Community", "color": "#90A4AE", "icon": "person.3", "priority": 2},
    "business": {"label": "Business", "color": "#4DD0E1", "icon": "briefcase", "priority": 3},
    "cultural": {"label": "Cultural", "color": "#FF8A65", "icon": "theatermasks", "priority": 3},
    "local": {"label": "Local", "color": "#95A5A6", "icon": "mappin", "priority": 1},
}


# ── Public Holidays (Calendarific or hardcoded) ──────────────────────

# Major holidays per country (hardcoded fallback if no API key)
HOLIDAYS_BY_COUNTRY = {
    "CA": [
        {"month": 1, "day": 1, "title": "New Year's Day"},
        {"month": 2, "day": 17, "title": "Family Day (AB)"},
        {"month": 4, "day": 18, "title": "Good Friday"},
        {"month": 5, "day": 19, "title": "Victoria Day"},
        {"month": 7, "day": 1, "title": "Canada Day"},
        {"month": 8, "day": 4, "title": "Heritage Day (AB)"},
        {"month": 9, "day": 1, "title": "Labour Day"},
        {"month": 10, "day": 13, "title": "Thanksgiving"},
        {"month": 11, "day": 11, "title": "Remembrance Day"},
        {"month": 12, "day": 25, "title": "Christmas Day"},
        {"month": 12, "day": 26, "title": "Boxing Day"},
    ],
    "PA": [
        {"month": 1, "day": 1, "title": "New Year's Day"},
        {"month": 1, "day": 9, "title": "Martyrs' Day"},
        {"month": 5, "day": 1, "title": "Labour Day"},
        {"month": 11, "day": 3, "title": "Separation Day"},
        {"month": 11, "day": 4, "title": "Flag Day"},
        {"month": 11, "day": 5, "title": "Colon Day"},
        {"month": 11, "day": 10, "title": "Los Santos Uprising"},
        {"month": 11, "day": 28, "title": "Independence from Spain"},
        {"month": 12, "day": 8, "title": "Mother's Day"},
        {"month": 12, "day": 25, "title": "Christmas Day"},
    ],
    "SV": [
        {"month": 1, "day": 1, "title": "New Year's Day"},
        {"month": 5, "day": 1, "title": "Labour Day"},
        {"month": 5, "day": 10, "title": "Mother's Day"},
        {"month": 6, "day": 17, "title": "Father's Day"},
        {"month": 8, "day": 1, "title": "Fiestas Agostinas Begin"},
        {"month": 8, "day": 6, "title": "Feast of San Salvador"},
        {"month": 9, "day": 15, "title": "Independence Day"},
        {"month": 11, "day": 2, "title": "Day of the Dead"},
        {"month": 12, "day": 25, "title": "Christmas Day"},
    ],
    "UY": [
        {"month": 1, "day": 1, "title": "New Year's Day"},
        {"month": 1, "day": 6, "title": "Children's Day"},
        {"month": 4, "day": 19, "title": "Landing of the 33"},
        {"month": 5, "day": 1, "title": "Labour Day"},
        {"month": 5, "day": 18, "title": "Battle of Las Piedras"},
        {"month": 6, "day": 19, "title": "Artigas Birthday"},
        {"month": 7, "day": 18, "title": "Constitution Day"},
        {"month": 8, "day": 25, "title": "Independence Day"},
        {"month": 10, "day": 12, "title": "Day of the Race"},
        {"month": 12, "day": 25, "title": "Christmas Day"},
    ],
    "PY": [
        {"month": 1, "day": 1, "title": "New Year's Day"},
        {"month": 3, "day": 1, "title": "Heroes' Day"},
        {"month": 5, "day": 1, "title": "Labour Day"},
        {"month": 5, "day": 14, "title": "Independence Day (Flag Day)"},
        {"month": 5, "day": 15, "title": "Independence Day"},
        {"month": 6, "day": 12, "title": "Chaco Armistice"},
        {"month": 8, "day": 15, "title": "Founding of Asuncion"},
        {"month": 9, "day": 29, "title": "Battle of Boqueron"},
        {"month": 12, "day": 8, "title": "Virgin of Caacupe"},
        {"month": 12, "day": 25, "title": "Christmas Day"},
    ],
    "MX": [
        {"month": 1, "day": 1, "title": "New Year's Day"},
        {"month": 2, "day": 5, "title": "Constitution Day"},
        {"month": 3, "day": 21, "title": "Benito Juarez Birthday"},
        {"month": 5, "day": 1, "title": "Labour Day"},
        {"month": 5, "day": 5, "title": "Cinco de Mayo"},
        {"month": 9, "day": 16, "title": "Independence Day"},
        {"month": 10, "day": 12, "title": "Day of the Race"},
        {"month": 11, "day": 1, "title": "Day of the Dead"},
        {"month": 11, "day": 2, "title": "Day of the Dead"},
        {"month": 11, "day": 20, "title": "Revolution Day"},
        {"month": 12, "day": 25, "title": "Christmas Day"},
    ],
}


def get_holidays(city_id: str, start: date, end: date) -> list[dict]:
    """Get public holidays for a city's country in the date range."""
    city = CITIES.get(city_id)
    if not city:
        return []

    country = city["country"]
    holidays = HOLIDAYS_BY_COUNTRY.get(country, [])
    events = []

    for h in holidays:
        for year in range(start.year, end.year + 1):
            try:
                hdate = date(year, h["month"], h["day"])
            except ValueError:
                continue
            if start <= hdate <= end:
                events.append({
                    "date": hdate.isoformat(),
                    "title": h["title"],
                    "category": "holiday",
                    "city": city_id,
                    "city_name": city["name"],
                    "country": country,
                    "description": f"Public holiday in {city['country_name']}",
                    "impact": "medium",
                    "all_day": True,
                })

    return events


# ── Weather Alerts (Open-Meteo — free, no key needed) ────────────────

async def get_weather_alerts(city_id: str, start: date, end: date) -> list[dict]:
    """Get notable weather conditions from Open-Meteo forecast."""
    city = CITIES.get(city_id)
    if not city:
        return []

    cache_key = f"weather_{city_id}_{start}_{end}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data

    events = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            # Only forecast up to 16 days ahead
            forecast_end = min(end, date.today() + timedelta(days=15))
            if forecast_end < start:
                return []

            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": city["lat"],
                    "longitude": city["lon"],
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code",
                    "start_date": start.isoformat(),
                    "end_date": forecast_end.isoformat(),
                    "timezone": city["timezone"],
                },
            )
            if resp.status_code != 200:
                log.warning("Open-Meteo API returned %d for %s", resp.status_code, city_id)
                return []

            data = resp.json()
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            temps_max = daily.get("temperature_2m_max", [])
            temps_min = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])
            wind = daily.get("wind_speed_10m_max", [])
            codes = daily.get("weather_code", [])

            for i, d in enumerate(dates):
                notable = []
                impact = "low"

                t_max = temps_max[i] if i < len(temps_max) else None
                t_min = temps_min[i] if i < len(temps_min) else None
                p = precip[i] if i < len(precip) else 0
                w = wind[i] if i < len(wind) else 0
                code = codes[i] if i < len(codes) else 0

                # Flag notable conditions
                if t_max is not None and t_max >= 35:
                    notable.append(f"Extreme heat: {t_max:.0f}C")
                    impact = "high"
                elif t_min is not None and t_min <= -25:
                    notable.append(f"Extreme cold: {t_min:.0f}C")
                    impact = "high"

                if p and p >= 20:
                    notable.append(f"Heavy rain: {p:.0f}mm")
                    impact = "high" if p >= 50 else "medium"
                elif p and p >= 5:
                    notable.append(f"Rain: {p:.0f}mm")

                if w and w >= 60:
                    notable.append(f"High wind: {w:.0f} km/h")
                    impact = "high"

                # Thunderstorm codes (95-99)
                if code and code >= 95:
                    notable.append("Thunderstorm expected")
                    impact = "high"
                # Snow codes (71-77, 85-86)
                elif code and code in (71, 73, 75, 77, 85, 86):
                    notable.append("Snowfall expected")
                    if code in (75, 86):
                        impact = "medium"

                if notable:
                    desc_parts = []
                    if t_max is not None and t_min is not None:
                        desc_parts.append(f"High {t_max:.0f}C / Low {t_min:.0f}C")
                    desc_parts.extend(notable)

                    events.append({
                        "date": d,
                        "title": " | ".join(notable[:2]),
                        "category": "weather",
                        "city": city_id,
                        "city_name": city["name"],
                        "description": " -- ".join(desc_parts),
                        "impact": impact,
                        "all_day": True,
                    })

    except Exception as e:
        log.error("Open-Meteo error for %s: %s", city_id, e)

    _cache[cache_key] = (time.time(), events)
    return events


# ── Ticketmaster Events (concerts, sports, shows) ────────────────────

async def get_ticketmaster_events(city_id: str, start: date, end: date) -> list[dict]:
    """Fetch events from Ticketmaster Discovery API."""
    city = CITIES.get(city_id)
    if not city:
        return []

    api_key = os.environ.get("TICKETMASTER_API_KEY", "")
    if not api_key:
        log.debug("No TICKETMASTER_API_KEY — skipping Ticketmaster for %s", city_id)
        return []

    cache_key = f"ticketmaster_{city_id}_{start}_{end}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data

    events = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                "https://app.ticketmaster.com/discovery/v2/events.json",
                params={
                    "apikey": api_key,
                    "latlong": f"{city['lat']},{city['lon']}",
                    "radius": "50",
                    "unit": "km",
                    "startDateTime": f"{start.isoformat()}T00:00:00Z",
                    "endDateTime": f"{end.isoformat()}T23:59:59Z",
                    "size": 20,
                    "sort": "date,asc",
                },
            )
            if resp.status_code != 200:
                log.warning("Ticketmaster API returned %d for %s", resp.status_code, city_id)
                return []

            data = resp.json()
            for item in data.get("_embedded", {}).get("events", []):
                event_date = item.get("dates", {}).get("start", {}).get("localDate", "")
                event_time = item.get("dates", {}).get("start", {}).get("localTime", "")

                # Classify by segment
                segment = ""
                for c in item.get("classifications", []):
                    segment = c.get("segment", {}).get("name", "").lower()
                    break

                if "sport" in segment:
                    cat = "sports"
                elif "music" in segment:
                    cat = "concert"
                elif "arts" in segment or "theatre" in segment:
                    cat = "cultural"
                else:
                    cat = "community"

                venue_name = ""
                for v in item.get("_embedded", {}).get("venues", []):
                    venue_name = v.get("name", "")
                    break

                events.append({
                    "date": event_date,
                    "title": item.get("name", ""),
                    "category": cat,
                    "city": city_id,
                    "city_name": city["name"],
                    "description": f"{venue_name}" if venue_name else "",
                    "impact": "low",
                    "all_day": not bool(event_time),
                    "time": event_time[:5] if event_time else "",
                    "url": item.get("url", ""),
                })

    except Exception as e:
        log.error("Ticketmaster error for %s: %s", city_id, e)

    _cache[cache_key] = (time.time(), events)
    return events


# ── Custom curated local events ──────────────────────────────────────

_LOCAL_EVENTS_PATH = os.path.expanduser("~/NCL/data/calendar/local_events.jsonl")


def _load_curated_events(city_id: str, start: date, end: date) -> list[dict]:
    """Load manually curated local events from JSONL file."""
    if not os.path.exists(_LOCAL_EVENTS_PATH):
        return []

    events = []
    try:
        with open(_LOCAL_EVENTS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("city") != city_id:
                    continue
                event_date = date.fromisoformat(event.get("date", ""))
                if start <= event_date <= end:
                    events.append(event)
    except Exception as e:
        log.error("Error loading curated local events: %s", e)

    return events


def add_local_event(event: dict) -> dict:
    """Add a curated local event to the JSONL store."""
    os.makedirs(os.path.dirname(_LOCAL_EVENTS_PATH), exist_ok=True)

    event.setdefault("category", "local")
    event.setdefault("impact", "low")
    event.setdefault("all_day", True)
    event["created_at"] = datetime.now(timezone.utc).isoformat()

    with open(_LOCAL_EVENTS_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")

    log.info("Local event added: %s on %s in %s", event.get("title"), event.get("date"), event.get("city"))
    return event


# ── Combined local events ────────────────────────────────────────────

async def get_local_events(
    city_id: str,
    start: date,
    end: date,
) -> list[dict]:
    """
    Get all local events for a city — holidays + weather + ticketmaster + curated.
    Enriches each event with category metadata.
    """
    city = CITIES.get(city_id)
    if not city:
        return []

    events = get_holidays(city_id, start, end)

    # Weather (free, always available)
    weather = await get_weather_alerts(city_id, start, end)
    events.extend(weather)

    # Ticketmaster (needs API key)
    tm = await get_ticketmaster_events(city_id, start, end)
    events.extend(tm)

    # Curated local events
    curated = _load_curated_events(city_id, start, end)
    events.extend(curated)

    # Enrich with category metadata
    for event in events:
        cat = event.get("category", "local")
        meta = LOCAL_EVENT_CATEGORIES.get(cat, LOCAL_EVENT_CATEGORIES["local"])
        event["category_label"] = meta["label"]
        event["category_color"] = meta["color"]
        event["category_icon"] = meta["icon"]
        event["priority"] = meta["priority"]

    # Sort by date, then priority
    events.sort(key=lambda e: (e["date"], -e.get("priority", 0)))

    return events


def get_cities_list() -> list[dict]:
    """Return list of available cities with metadata."""
    return [
        {
            "id": city_id,
            "name": city["name"],
            "country": city["country"],
            "country_name": city["country_name"],
            "icon": city["icon"],
            "color": city["color"],
        }
        for city_id, city in CITIES.items()
    ]


# ── Rich per-city payload (events + landmarks + notable + fun_finder) ─

async def get_city_payload(
    city_id: str,
    start: date,
    end: date,
    use_scanner_cache: bool = True,
) -> dict:
    """
    Rich per-city payload — superset of get_local_events.

    Returns:
        {
            "city": str,                          # city_id
            "city_name": str,
            "country": str,
            "weather": {...} | None,              # latest weather event summary
            "events": [...],                      # holidays + weather + tm + curated + scanner sources
            "landmarks": [...],
            "notable_dates": [...],
            "fun_finder": {
                "today": [...],
                "this_week": [...],
                "this_month": [...],
            },
            "stats": {...},
            "sources_used": [str],
        }

    Augments — does NOT replace — `get_local_events()`. Existing callers that
    expect a flat list continue to use `get_local_events()`.
    """
    city = CITIES.get(city_id)
    if not city:
        return {"city": city_id, "error": f"unknown city: {city_id}"}

    # Existing path: holidays + weather + TM + curated
    base_events = await get_local_events(city_id, start, end)

    # New: city_scanner — eventbrite + reddit + trends + news + bootstrap notable + landmarks
    scanner_payload: dict = {}
    try:
        # Local import to avoid a hard dep if city_scanner is being refactored
        from .city_scanner import get_city_scanner
        scanner = get_city_scanner()
        # Compute the lookahead delta the scanner expects (it owns its own window)
        lookahead = max(1, (end - date.today()).days)
        lookback = max(0, (date.today() - start).days)
        scanner_payload = await scanner.scan_city(
            city_id,
            lookback_days=lookback,
            lookahead_days=lookahead,
            bypass_cache=not use_scanner_cache,
        )
    except Exception as e:
        log.warning("city_scanner.scan_city failed for %s: %s", city_id, e)
        scanner_payload = {}

    scanner_events = scanner_payload.get("events", []) or []

    # Merge + dedup against base_events by (date, lowercased-title)
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for ev in base_events + scanner_events:
        key = (ev.get("date", ""), (ev.get("title") or "")[:80].lower().strip())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(ev)

    # Re-sort
    merged.sort(key=lambda e: (e.get("date", ""), -e.get("priority", 0)))

    # Fun-finder bucketing
    today = date.today()
    today_iso = today.isoformat()
    week_end_iso = (today + timedelta(days=7)).isoformat()
    month_end_iso = (today + timedelta(days=30)).isoformat()
    fun_finder = {
        "today": [e for e in merged if e.get("date") == today_iso],
        "this_week": [e for e in merged if today_iso < e.get("date", "") <= week_end_iso],
        "this_month": [e for e in merged if week_end_iso < e.get("date", "") <= month_end_iso],
    }

    # Pull most-recent weather event as a summary block (for iOS header)
    weather_summary = None
    for e in base_events:
        if e.get("category") == "weather" and e.get("date") == today_iso:
            weather_summary = {
                "title": e.get("title", ""),
                "description": e.get("description", ""),
                "impact": e.get("impact", "low"),
            }
            break

    return {
        "city": city_id,
        "city_name": city["name"],
        "country": city["country"],
        "country_name": city["country_name"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather": weather_summary,
        "events": merged,
        "count": len(merged),
        "landmarks": scanner_payload.get("landmarks", []),
        "notable_dates": scanner_payload.get("notable_dates", []),
        "fun_finder": fun_finder,
        "stats": {
            "total_events": len(merged),
            "today_count": len(fun_finder["today"]),
            "this_week_count": len(fun_finder["this_week"]),
            "this_month_count": len(fun_finder["this_month"]),
            "landmark_count": len(scanner_payload.get("landmarks", []) or []),
            "notable_dates_count": len(scanner_payload.get("notable_dates", []) or []),
        },
        "sources_used": ["holidays", "weather", "ticketmaster", "curated"]
                        + scanner_payload.get("sources_used", []),
    }
