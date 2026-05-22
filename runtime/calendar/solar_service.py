"""
Solar & Space Weather Service for NCL Brain.

Fetches, caches, and serves:
  - Sunrise/sunset/twilight per city (sunrise-sunset.org, free, no key)
  - Space weather from NOAA SWPC (free, no key) — Kp, solar wind, X-ray, alerts
  - Sunspot data and F10.7 radio flux
  - Aurora forecast (ovation + 3-day Kp text forecast)
  - CME / geomagnetic storm alerts
  - Schumann Resonance (stub — estimated baseline; no reliable free API)
  - Seasonal marker (equinox/solstice via Skyfield with pure-math fallback)
  - Composite full_solar_state for SunView / Calendar Agent
  - Daily snapshot persistence (data/calendar/solar_snapshots.jsonl)

Cities: Edmonton, Calgary, Panama City, San Salvador, Montevideo, Asuncion, Oaxaca

All HTTP calls have a 10s timeout and a stale-cache fallback —
on transient API failure we return the last successful payload
flagged with `stale: true` rather than empty data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp

log = logging.getLogger("ncl.calendar.solar")

# ── City Coordinates ────────────────────────────────────────────────
# Keys match local_events.py city IDs exactly.

CITY_COORDS: dict[str, dict[str, Any]] = {
    "edmonton": {
        "name": "Edmonton",
        "lat": 53.5461,
        "lon": -113.4937,
        "timezone": "America/Edmonton",
    },
    "calgary": {
        "name": "Calgary",
        "lat": 51.0447,
        "lon": -114.0719,
        "timezone": "America/Edmonton",
    },
    "panama_city": {
        "name": "Panama City",
        "lat": 8.9824,
        "lon": -79.5199,
        "timezone": "America/Panama",
    },
    "san_salvador": {
        "name": "San Salvador",
        "lat": 13.6929,
        "lon": -89.2182,
        "timezone": "America/El_Salvador",
    },
    "montevideo": {
        "name": "Montevideo",
        "lat": -34.9011,
        "lon": -56.1645,
        "timezone": "America/Montevideo",
    },
    "asuncion": {
        "name": "Asuncion",
        "lat": -25.2637,
        "lon": -57.5759,
        "timezone": "America/Asuncion",
    },
    "oaxaca": {
        "name": "Oaxaca",
        "lat": 17.0732,
        "lon": -96.7266,
        "timezone": "America/Mexico_City",
    },
}

# ── Cache ───────────────────────────────────────────────────────────
# Two-layer:
#   _solar_cache       — TTL-respecting, returned on cache hit
#   _stale_cache       — last-good payload, no expiry; returned with stale=true
#                        when a live fetch fails

_solar_cache: dict[str, tuple[float, Any]] = {}
_stale_cache: dict[str, Any] = {}

# TTLs in seconds
_TTL_SUNRISE = 86400       # 24h — changes daily
_TTL_SPACE_WEATHER = 900   # 15m — Kp, solar wind, X-ray
_TTL_SUNSPOT = 21600       # 6h
_TTL_SOLAR_CALENDAR = 86400  # 24h
_TTL_AURORA = 1800         # 30m
_TTL_CME = 900             # 15m
_TTL_SCHUMANN = 3600       # 1h
_TTL_SEASONAL = 86400      # 24h

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Snapshot persistence
_SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "calendar"
_SNAPSHOT_PATH = _SNAPSHOT_DIR / "solar_snapshots.jsonl"


def _cache_get(key: str) -> Optional[Any]:
    """Return cached value if present and not expired, else None."""
    entry = _solar_cache.get(key)
    if entry is None:
        return None
    expiry, data = entry
    if time.time() > expiry:
        return None
    return data


def _cache_set(key: str, data: Any, ttl: int) -> None:
    """Store data in cache with TTL (seconds from now) and update stale-cache."""
    _solar_cache[key] = (time.time() + ttl, data)
    _stale_cache[key] = data


def _stale_or(key: str, fallback: dict) -> dict:
    """Return stale cached payload tagged with stale:true, or `fallback`."""
    last = _stale_cache.get(key)
    if last is not None:
        out = dict(last) if isinstance(last, dict) else {"data": last}
        out["stale"] = True
        return out
    return fallback


# ── Sunrise / Sunset / Twilight ─────────────────────────────────────

async def _fetch_sunrise_sunset(lat: float, lon: float, dt: date) -> dict:
    """
    Fetch sunrise/sunset/twilight from sunrise-sunset.org.

    Returns a dict including astronomical/nautical/civil twilight ranges,
    solar_noon, golden_hour, and day_length_seconds. All times UTC ISO-8601.
    """
    url = "https://api.sunrise-sunset.org/json"
    params = {
        "lat": lat,
        "lng": lon,
        "date": dt.isoformat(),
        "formatted": 0,  # ISO 8601 format
    }
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    log.warning("sunrise-sunset.org returned %d", resp.status)
                    return _sunrise_defaults()
                body = await resp.json()
                if body.get("status") != "OK":
                    log.warning("sunrise-sunset.org status: %s", body.get("status"))
                    return _sunrise_defaults()
                r = body["results"]
                return {
                    "sunrise": r.get("sunrise"),
                    "sunset": r.get("sunset"),
                    "solar_noon": r.get("solar_noon"),
                    "golden_hour": r.get("golden_hour"),
                    "day_length_seconds": r.get("day_length"),
                    "civil_twilight_begin": r.get("civil_twilight_begin"),
                    "civil_twilight_end": r.get("civil_twilight_end"),
                    "nautical_twilight_begin": r.get("nautical_twilight_begin"),
                    "nautical_twilight_end": r.get("nautical_twilight_end"),
                    "astronomical_twilight_begin": r.get("astronomical_twilight_begin"),
                    "astronomical_twilight_end": r.get("astronomical_twilight_end"),
                }
    except Exception as exc:
        log.error("sunrise-sunset.org fetch failed: %s", exc)
        return _sunrise_defaults()


def _sunrise_defaults() -> dict:
    """Fallback values when sunrise API is unavailable."""
    return {
        "sunrise": None,
        "sunset": None,
        "solar_noon": None,
        "golden_hour": None,
        "day_length_seconds": None,
        "civil_twilight_begin": None,
        "civil_twilight_end": None,
        "nautical_twilight_begin": None,
        "nautical_twilight_end": None,
        "astronomical_twilight_begin": None,
        "astronomical_twilight_end": None,
        "error": "API unavailable",
    }


async def get_sun_times(city_id: str, target_date: Optional[date] = None) -> dict:
    """
    Sunrise, sunset, solar noon, civil/nautical/astronomical twilight,
    golden hour, and day length for a city on a given date (default: today).
    """
    city = CITY_COORDS.get(city_id)
    if city is None:
        return {"error": f"Unknown city: {city_id}", "city_id": city_id}

    dt = target_date or date.today()
    cache_key = f"sun_times:{city_id}:{dt.isoformat()}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _fetch_sunrise_sunset(city["lat"], city["lon"], dt)
    if "error" in data:
        return _stale_or(cache_key, {**data, "city_id": city_id, "city": city["name"]})

    data["city"] = city["name"]
    data["city_id"] = city_id
    data["date"] = dt.isoformat()
    data["lat"] = city["lat"]
    data["lon"] = city["lon"]
    _cache_set(cache_key, data, _TTL_SUNRISE)
    return data


# Backwards-compatible alias used by older callers.
async def get_sunrise_sunset(city_id: str) -> dict:
    return await get_sun_times(city_id, None)


# ── NOAA SWPC fetch helpers ─────────────────────────────────────────

async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Any:
    """Generic JSON fetch with error handling."""
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                log.warning("SWPC %s returned %d", url, resp.status)
                return None
            return await resp.json(content_type=None)
    except Exception as exc:
        log.error("SWPC fetch failed for %s: %s", url, exc)
        return None


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Generic text fetch with error handling."""
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                log.warning("SWPC %s returned %d", url, resp.status)
                return None
            return await resp.text()
    except Exception as exc:
        log.error("SWPC fetch failed for %s: %s", url, exc)
        return None


# ── Space Weather: Kp Index ─────────────────────────────────────────

async def _fetch_kp_index() -> dict:
    """Latest Kp index values from NOAA planetary-k-index feed.

    The NOAA endpoint returns either:
      - List of dicts: [{"time_tag":..., "Kp":..., "a_running":..., "station_count":...}, ...]
      - Legacy list-of-lists with a header row.
    We support both shapes.
    """
    cache_key = "space:kp"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, list) or len(data) == 0:
                return _stale_or(cache_key, _kp_defaults())

            entries: list[dict] = []
            first = data[0]
            if isinstance(first, dict):
                # New dict format.
                entries = data
            elif isinstance(first, list):
                # Legacy: ["time_tag","Kp","a_running","station_count"] header row.
                rows = data[1:] if first and first[0] == "time_tag" else data
                for row in rows:
                    if not isinstance(row, list):
                        continue
                    entries.append({
                        "time_tag": row[0] if len(row) > 0 else None,
                        "Kp": row[1] if len(row) > 1 else None,
                        "a_running": row[2] if len(row) > 2 else None,
                        "station_count": row[3] if len(row) > 3 else None,
                    })

            if not entries:
                return _stale_or(cache_key, _kp_defaults())

            recent_entries = entries[-8:]
            parsed = []
            for row in recent_entries:
                parsed.append({
                    "time_tag": row.get("time_tag"),
                    "kp": _safe_float(row.get("Kp") if "Kp" in row else row.get("kp")),
                    "a_running": _safe_float(row.get("a_running")),
                    "station_count": _safe_int(row.get("station_count")),
                })

            current_kp = parsed[-1]["kp"] if parsed else None
            storm_level = _kp_storm_level(current_kp)

            result = {
                "current_kp": current_kp,
                "storm_level": storm_level,
                "recent_entries": parsed,
                "source": "NOAA SWPC",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_SPACE_WEATHER)
            return result
    except Exception as exc:
        log.error("Kp index fetch failed: %s", exc)
        return _stale_or(cache_key, _kp_defaults())


def _kp_storm_level(kp: Optional[float]) -> str:
    """Classify Kp value into NOAA G-scale storm level."""
    if kp is None:
        return "unknown"
    if kp < 4:
        return "quiet"
    if kp < 5:
        return "unsettled"
    if kp < 6:
        return "G1_minor_storm"
    if kp < 7:
        return "G2_moderate_storm"
    if kp < 8:
        return "G3_strong_storm"
    if kp < 9:
        return "G4_severe_storm"
    return "G5_extreme_storm"


def _kp_defaults() -> dict:
    return {
        "current_kp": None,
        "storm_level": "unknown",
        "recent_entries": [],
        "source": "NOAA SWPC",
        "error": "unavailable",
    }


# ── Space Weather: Solar Wind ───────────────────────────────────────

async def _fetch_solar_wind() -> dict:
    """Latest solar wind speed and density from plasma-1-day feed."""
    cache_key = "space:solar_wind"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, list) or len(data) < 2:
                return _stale_or(cache_key, _solar_wind_defaults())

            # Header: ["time_tag", "density", "speed", "temperature"]
            entries = data[1:]
            # Walk backwards to find a row with real numeric speed (NOAA emits "null").
            latest = None
            for row in reversed(entries):
                if len(row) >= 3 and _safe_float(row[2]) is not None:
                    latest = row
                    break
            if latest is None:
                latest = entries[-1]

            speed = _safe_float(latest[2]) if len(latest) > 2 else None
            density = _safe_float(latest[1]) if len(latest) > 1 else None
            temperature = _safe_float(latest[3]) if len(latest) > 3 else None
            time_tag = latest[0] if len(latest) > 0 else None

            result = {
                "speed_km_s": speed,
                "density_p_cm3": density,
                "temperature_k": temperature,
                "time_tag": time_tag,
                "wind_band": _wind_band(speed),
                "source": "NOAA SWPC",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_SPACE_WEATHER)
            return result
    except Exception as exc:
        log.error("Solar wind fetch failed: %s", exc)
        return _stale_or(cache_key, _solar_wind_defaults())


def _wind_band(speed: Optional[float]) -> str:
    if speed is None:
        return "unknown"
    if speed < 400:
        return "slow"
    if speed < 500:
        return "moderate"
    if speed < 700:
        return "elevated"
    return "high"


def _solar_wind_defaults() -> dict:
    return {
        "speed_km_s": None,
        "density_p_cm3": None,
        "temperature_k": None,
        "wind_band": "unknown",
        "source": "NOAA SWPC",
        "error": "unavailable",
    }


# ── Space Weather: X-ray flux / flare class ─────────────────────────

async def _fetch_xray_flux() -> dict:
    """Latest X-ray flux (solar flare class) from GOES primary."""
    cache_key = "space:xray"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, list) or len(data) == 0:
                return _stale_or(cache_key, _xray_defaults())

            # Prefer the long-wavelength channel (0.1-0.8 nm) which is used for
            # flare classification. Walk from newest backwards.
            latest = None
            for entry in reversed(data):
                energy = (entry.get("energy") or "").lower()
                if "0.1-0.8" in energy or "long" in energy:
                    latest = entry
                    break
            if latest is None:
                latest = data[-1]

            flux = _safe_float(latest.get("flux"))
            flare_class = _classify_xray_flux(flux)

            result = {
                "time_tag": latest.get("time_tag"),
                "flux_w_m2": flux,
                "flare_class": flare_class,
                "energy": latest.get("energy"),
                "satellite": latest.get("satellite"),
                "source": "NOAA SWPC / GOES",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_SPACE_WEATHER)
            return result
    except Exception as exc:
        log.error("X-ray flux fetch failed: %s", exc)
        return _stale_or(cache_key, _xray_defaults())


def _classify_xray_flux(flux: Optional[float]) -> str:
    """Classify X-ray flux into solar flare class (A/B/C/M/X)."""
    if flux is None or flux <= 0:
        return "unknown"
    if flux < 1e-7:
        return "A"
    if flux < 1e-6:
        return "B"
    if flux < 1e-5:
        return "C"
    if flux < 1e-4:
        return "M"
    return "X"


def _flare_class_rank(cls: str) -> int:
    """Numeric rank for flare class (used in solar_energy_mode)."""
    return {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}.get(cls.upper(), -1) if cls else -1


def _xray_defaults() -> dict:
    return {
        "flux_w_m2": None,
        "flare_class": "unknown",
        "source": "NOAA SWPC / GOES",
        "error": "unavailable",
    }


# ── Space Weather: Proton flux ──────────────────────────────────────

async def _fetch_proton_flux() -> dict:
    """Latest >=10 MeV proton flux from GOES integral protons."""
    cache_key = "space:proton"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, list) or len(data) == 0:
                return _stale_or(cache_key, {"proton_flux": None, "source": "NOAA SWPC", "error": "unavailable"})

            # Prefer the >=10 MeV channel.
            latest = None
            for entry in reversed(data):
                energy = (entry.get("energy") or "").lower()
                if ">=10" in energy or "10 mev" in energy or "ge10" in energy:
                    latest = entry
                    break
            if latest is None:
                latest = data[-1]

            flux = _safe_float(latest.get("flux"))
            result = {
                "time_tag": latest.get("time_tag"),
                "flux_pfu": flux,
                "energy": latest.get("energy"),
                "satellite": latest.get("satellite"),
                "alert_level": _proton_alert_level(flux),
                "source": "NOAA SWPC / GOES",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_SPACE_WEATHER)
            return result
    except Exception as exc:
        log.error("Proton flux fetch failed: %s", exc)
        return _stale_or(cache_key, {"flux_pfu": None, "source": "NOAA SWPC", "error": "unavailable"})


def _proton_alert_level(flux: Optional[float]) -> str:
    """NOAA S-scale equivalent for >=10 MeV proton flux."""
    if flux is None:
        return "unknown"
    if flux < 10:
        return "none"
    if flux < 100:
        return "S1_minor"
    if flux < 1000:
        return "S2_moderate"
    if flux < 10000:
        return "S3_strong"
    if flux < 100000:
        return "S4_severe"
    return "S5_extreme"


# ── Space Weather composite ─────────────────────────────────────────

async def get_space_weather() -> dict:
    """
    Current Kp, solar wind (speed + density), X-ray flux + flare class,
    and >=10 MeV proton flux. Caches per-source with 15-min TTL.
    """
    results = await asyncio.gather(
        _fetch_kp_index(),
        _fetch_solar_wind(),
        _fetch_xray_flux(),
        _fetch_proton_flux(),
        return_exceptions=True,
    )

    def _safe(r: Any, default: dict) -> dict:
        if isinstance(r, Exception):
            log.error("Space weather gather raised: %s", r)
            return default
        return r if isinstance(r, dict) else default

    kp = _safe(results[0], _kp_defaults())
    wind = _safe(results[1], _solar_wind_defaults())
    xray = _safe(results[2], _xray_defaults())
    proton = _safe(results[3], {"flux_pfu": None, "source": "NOAA SWPC", "error": "unavailable"})

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kp_index": kp,
        "solar_wind": wind,
        "xray_flux": xray,
        "proton_flux": proton,
    }


# ── Sunspot / F10.7 ─────────────────────────────────────────────────

async def _fetch_sunspot_number() -> dict:
    """Daily sunspot number from SWPC summary endpoint."""
    cache_key = "space:sunspot_number"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # daily-solar-indices.json contains the official daily sunspot number (SSN).
    url = "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, list) or len(data) == 0:
                return _stale_or(cache_key, {"ssn": None, "source": "NOAA SWPC", "error": "unavailable"})

            latest = data[-1]
            result = {
                "time_tag": latest.get("time-tag"),
                "ssn": _safe_float(latest.get("ssn")),
                "smoothed_ssn": _safe_float(latest.get("smoothed_ssn")),
                "source": "NOAA SWPC",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_SUNSPOT)
            return result
    except Exception as exc:
        log.error("Sunspot fetch failed: %s", exc)
        return _stale_or(cache_key, {"ssn": None, "source": "NOAA SWPC", "error": "unavailable"})


async def _fetch_f107_flux() -> dict:
    """F10.7 cm solar radio flux from SWPC summary."""
    cache_key = "space:f107"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/products/summary/10cm-flux.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data:
                return _stale_or(cache_key, {"f10_7": None, "source": "NOAA SWPC", "error": "unavailable"})

            # SWPC has shipped this endpoint as both a list ([{flux, time_tag}])
            # and a dict ({Flux, TimeStamp}). Support both.
            payload: dict
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                payload = data[-1]
            elif isinstance(data, dict):
                payload = data
            else:
                return _stale_or(cache_key, {"f10_7": None, "source": "NOAA SWPC", "error": "unavailable"})

            flux = _safe_float(payload.get("flux", payload.get("Flux")))
            ts = payload.get("time_tag", payload.get("TimeStamp"))
            result = {
                "f10_7": flux,
                "time_stamp": ts,
                "source": "NOAA SWPC",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_SUNSPOT)
            return result
    except Exception as exc:
        log.error("F10.7 fetch failed: %s", exc)
        return _stale_or(cache_key, {"f10_7": None, "source": "NOAA SWPC", "error": "unavailable"})


async def get_sunspot_data() -> dict:
    """Daily sunspot number + F10.7 radio flux (6h cache)."""
    ssn, f107 = await asyncio.gather(
        _fetch_sunspot_number(),
        _fetch_f107_flux(),
        return_exceptions=True,
    )
    if isinstance(ssn, Exception):
        ssn = {"ssn": None, "error": "unavailable"}
    if isinstance(f107, Exception):
        f107 = {"f10_7": None, "error": "unavailable"}

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sunspot_number": ssn,
        "f10_7_flux": f107,
    }


# ── Aurora forecast ─────────────────────────────────────────────────

async def _fetch_aurora_ovation() -> dict:
    """Ovation aurora model — global aurora probability grid."""
    cache_key = "aurora:ovation"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, dict):
                return _stale_or(cache_key, {"coordinates": [], "source": "NOAA SWPC", "error": "unavailable"})

            result = {
                "observation_time": data.get("Observation Time"),
                "forecast_time": data.get("Forecast Time"),
                "coordinates": data.get("coordinates", []),
                "source": "NOAA SWPC",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_AURORA)
            return result
    except Exception as exc:
        log.error("Ovation aurora fetch failed: %s", exc)
        return _stale_or(cache_key, {"coordinates": [], "source": "NOAA SWPC", "error": "unavailable"})


async def _fetch_3day_kp_forecast() -> dict:
    """3-day Kp forecast text feed from SWPC (parsed)."""
    cache_key = "aurora:kp_3day"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/text/3-day-forecast.txt"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            text = await _fetch_text(session, url)
            if not text:
                return _stale_or(cache_key, {"max_kp_3day": None, "forecast": [], "source": "NOAA SWPC", "error": "unavailable"})

            forecast = _parse_3day_kp_forecast(text)
            result = {
                "forecast": forecast,
                "max_kp_3day": max((f["max_kp"] for f in forecast if f.get("max_kp") is not None), default=None),
                "raw_excerpt": text[:1500],
                "source": "NOAA SWPC",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _cache_set(cache_key, result, _TTL_AURORA)
            return result
    except Exception as exc:
        log.error("3-day Kp forecast fetch failed: %s", exc)
        return _stale_or(cache_key, {"max_kp_3day": None, "forecast": [], "source": "NOAA SWPC", "error": "unavailable"})


def _parse_3day_kp_forecast(text: str) -> list[dict]:
    """
    Parse the SWPC 3-day forecast text. We extract per-day max Kp.

    The text has a block introduced by either
      'NOAA Kp index forecast ...'  (older) or
      'NOAA Kp index breakdown ...' (current),
    followed by a header line with 3 dates (e.g. 'May 21  May 22  May 23')
    and 8 lines of '00-03UT  3.00  2.67  2.33'.
    """
    import re as _re

    lines = text.splitlines()
    in_kp_block = False
    day_headers: list[str] = []
    daily_max: dict[str, float] = {}
    daily_values: dict[str, list[float]] = {}

    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if ("NOAA KP INDEX FORECAST" in upper) or ("NOAA KP INDEX BREAKDOWN" in upper):
            in_kp_block = True
            continue
        if not in_kp_block:
            continue
        # Stop on next section header (B./C./D.) or solar-radiation block.
        if (_re.match(r"^[B-Z]\.\s", stripped)
                or "SOLAR RADIATION" in upper
                or "RADIO BLACKOUT" in upper):
            break
        if not stripped:
            continue
        # Day header line: contains month tokens, no 'UT' time tag.
        if not day_headers and any(m in stripped for m in months) and "UT" not in upper:
            parts = [p for p in _re.split(r"\s{2,}", stripped) if p]
            # Only the day labels (e.g. "May 22") should remain.
            day_parts = [p for p in parts if any(m in p for m in months)]
            if len(day_parts) >= 3:
                day_headers = day_parts[:3]
                for h in day_headers:
                    daily_values[h] = []
            continue
        # Time-interval rows: '00-03UT  3.00  2.67  2.33'
        if "UT" in stripped and day_headers and _re.match(r"^\d{2}-\d{2}UT", stripped):
            tokens = stripped.split()
            # First token is the time range, remaining tokens should be Kp values.
            value_tokens = tokens[1:]
            for h, tok in zip(day_headers, value_tokens[:3]):
                val = _safe_float(tok)
                if val is not None:
                    daily_values[h].append(val)

    for h, vals in daily_values.items():
        if vals:
            daily_max[h] = max(vals)

    return [
        {"date_label": h, "max_kp": daily_max.get(h), "values": daily_values.get(h, [])}
        for h in day_headers
    ]


def _aurora_visibility(latitude: float, kp: Optional[float]) -> str:
    """
    Rough rule-of-thumb visibility for a given latitude + Kp.
    Aurora oval extends ~roughly 65deg - (Kp * 1.5deg) magnetic latitude
    on the equatorward edge. We use geographic latitude as an approximation.
    """
    if kp is None:
        return "unknown"
    abs_lat = abs(latitude)
    oval_edge = 65.0 - (kp * 1.5)
    if abs_lat >= oval_edge:
        return "likely"
    if abs_lat >= oval_edge - 3:
        return "possible"
    if abs_lat >= oval_edge - 6:
        return "unlikely"
    return "no"


async def get_aurora_forecast(city_id: str) -> dict:
    """
    30-min ovation + 3-day Kp forecast + city-specific visibility likelihood.
    """
    city = CITY_COORDS.get(city_id)
    if city is None:
        return {"error": f"Unknown city: {city_id}", "city_id": city_id}

    ovation_task = _fetch_aurora_ovation()
    forecast_task = _fetch_3day_kp_forecast()
    kp_task = _fetch_kp_index()

    ovation, forecast, kp = await asyncio.gather(
        ovation_task, forecast_task, kp_task, return_exceptions=True,
    )

    if isinstance(ovation, Exception):
        ovation = {"coordinates": [], "error": "unavailable"}
    if isinstance(forecast, Exception):
        forecast = {"forecast": [], "max_kp_3day": None, "error": "unavailable"}
    if isinstance(kp, Exception):
        kp = _kp_defaults()

    current_kp = kp.get("current_kp")
    max_kp_3day = forecast.get("max_kp_3day")
    visibility_now = _aurora_visibility(city["lat"], current_kp)
    visibility_3day = _aurora_visibility(city["lat"], max_kp_3day)

    return {
        "city_id": city_id,
        "city": city["name"],
        "lat": city["lat"],
        "current_kp": current_kp,
        "max_kp_3day": max_kp_3day,
        "visibility_now": visibility_now,
        "visibility_3day_peak": visibility_3day,
        "ovation_observation_time": ovation.get("observation_time"),
        "ovation_forecast_time": ovation.get("forecast_time"),
        "kp_3day_forecast": forecast.get("forecast", []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── CME / Geomagnetic alerts ────────────────────────────────────────

CME_KEYWORDS = (
    "CME", "coronal mass ejection",
    "geomagnetic storm", "geomagnetic sudden impulse",
    "solar energetic particle", "proton event",
    "K-index", "X-ray", "M-class", "X-class",
    "Type II", "Type IV", "halo",
)


def _alert_severity(message: str, product_id: str) -> str:
    """
    Map an SWPC alert to a severity bucket using Kp-scale wording.
    """
    text = f"{message} {product_id}".upper()
    if "G5" in text or "EXTREME" in text:
        return "extreme"
    if "G4" in text or "SEVERE" in text:
        return "severe"
    if "G3" in text or "STRONG" in text:
        return "strong"
    if "G2" in text or "MODERATE" in text:
        return "moderate"
    if "G1" in text or "MINOR" in text:
        return "minor"
    if "WATCH" in text or "WARNING" in text:
        return "watch"
    return "info"


async def get_cme_alerts() -> list[dict]:
    """
    Active CME/flare alerts + geomagnetic storm warnings, severity-tagged.
    Returns a list (newest-first) capped at 20 entries.
    """
    cache_key = "alerts:cme"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://services.swpc.noaa.gov/products/alerts.json"
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            data = await _fetch_json(session, url)
            if not data or not isinstance(data, list):
                stale = _stale_cache.get(cache_key)
                return stale if isinstance(stale, list) else []

            filtered: list[dict] = []
            for alert in data:
                msg = alert.get("message", "") or ""
                product_id = alert.get("product_id", "") or ""
                blob_upper = (msg + " " + product_id).upper()
                if any(kw.upper() in blob_upper for kw in CME_KEYWORDS):
                    filtered.append({
                        "issue_datetime": alert.get("issue_datetime"),
                        "product_id": product_id,
                        "severity": _alert_severity(msg, product_id),
                        "message": msg[:1000],
                    })

            # Newest first, capped.
            filtered.sort(key=lambda a: a.get("issue_datetime") or "", reverse=True)
            filtered = filtered[:20]
            _cache_set(cache_key, filtered, _TTL_CME)
            return filtered
    except Exception as exc:
        log.error("CME alerts fetch failed: %s", exc)
        stale = _stale_cache.get(cache_key)
        return stale if isinstance(stale, list) else []


# ── Schumann Resonance (stub) ───────────────────────────────────────

def get_schumann_resonance() -> dict:
    """
    Schumann Resonance baseline values.

    No reliable free API exists for live Schumann data. Known potential sources:
      - HeartMath Institute GCI (Global Coherence Initiative) — partnership required
      - Tomsk State University monitoring station — manual data only
      - SAM (Space and Atmosphere Monitoring) project

    Returns the well-known 7.83 Hz fundamental + harmonics + a quiet-time
    amplitude estimate, with `is_estimated:true` so callers can flag it.
    1h cache for parity with other endpoints (cache miss is cheap here).
    """
    cache_key = "schumann"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    payload = {
        "fundamental_frequency_hz": 7.83,
        "harmonics_hz": [14.3, 20.8, 27.3, 33.8],
        "estimated_amplitude_pT": 1.0,
        "is_estimated": True,
        "last_fetched": None,
        "note": (
            "Baseline values only — no reliable free live API. "
            "Integrate HeartMath GCI / Tomsk feed when available."
        ),
        "source": "estimated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, payload, _TTL_SCHUMANN)
    return payload


# ── Seasonal marker (equinox/solstice + sun declination) ────────────

# Try Skyfield once at import time, same pattern as lunar.py.
_skyfield_available = False
_sf_ts = None
_sf_eph = None

try:  # pragma: no cover - import-time side-effect
    from skyfield.api import load as _sf_load
    from skyfield import almanac as _sf_almanac

    _sf_data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(_sf_data_dir, exist_ok=True)
    _sf_ts = _sf_load.timescale()
    _sf_bsp = os.path.join(_sf_data_dir, "de421.bsp")
    if os.path.exists(_sf_bsp):
        _sf_eph = _sf_load(_sf_bsp)
        _skyfield_available = True
        log.info("Skyfield loaded for solar service")
except Exception as exc:  # pragma: no cover
    log.warning("Skyfield unavailable for solar service: %s", exc)


def _sun_declination_deg(dt: datetime) -> float:
    """
    Approximate solar declination in degrees using a pure-math Spencer
    fourier series. Accurate to ~0.05 degrees, plenty for UI purposes.
    """
    day_of_year = dt.timetuple().tm_yday
    gamma = 2.0 * math.pi * (day_of_year - 1) / 365.0
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    return math.degrees(decl)


def _next_equinox_solstice(after: datetime) -> tuple[str, datetime]:
    """
    Return (name, datetime) of the next equinox/solstice after `after`.
    Uses Skyfield almanac if available, else picks the next of four
    pre-computed approximate UTC dates per year.
    """
    if _skyfield_available and _sf_eph is not None and _sf_ts is not None:
        try:
            t0 = _sf_ts.from_datetime(after.astimezone(timezone.utc))
            t1 = _sf_ts.from_datetime((after + timedelta(days=400)).astimezone(timezone.utc))
            times, events = _sf_almanac.find_discrete(
                t0, t1, _sf_almanac.seasons(_sf_eph)
            )
            if len(times) > 0:
                names = ["vernal_equinox", "summer_solstice", "autumnal_equinox", "winter_solstice"]
                first_time = times[0].utc_datetime()
                first_name = names[int(events[0])]
                return first_name, first_time
        except Exception as exc:  # pragma: no cover - degrade silently
            log.warning("Skyfield seasons failed, falling back: %s", exc)

    # Fallback: approximate fixed dates at 12:00 UTC.
    year = after.year
    candidates: list[tuple[str, datetime]] = []
    for yr in (year, year + 1):
        candidates.extend([
            ("vernal_equinox", datetime(yr, 3, 20, 12, 0, tzinfo=timezone.utc)),
            ("summer_solstice", datetime(yr, 6, 21, 12, 0, tzinfo=timezone.utc)),
            ("autumnal_equinox", datetime(yr, 9, 22, 12, 0, tzinfo=timezone.utc)),
            ("winter_solstice", datetime(yr, 12, 21, 12, 0, tzinfo=timezone.utc)),
        ])
    after_utc = after.astimezone(timezone.utc) if after.tzinfo else after.replace(tzinfo=timezone.utc)
    for name, dt in candidates:
        if dt > after_utc:
            return name, dt
    # Shouldn't reach here, but return last candidate as last resort.
    return candidates[-1]


def get_seasonal_marker(target_date: Optional[date] = None) -> dict:
    """
    Current season (Northern reference), next equinox/solstice with countdown,
    and sun declination in degrees. Result is hemisphere-agnostic — callers can
    flip the season label using their own latitude.
    """
    cache_key = f"seasonal:{(target_date or date.today()).isoformat()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = target_date or date.today()
    now = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc)
    declination = _sun_declination_deg(now)

    name, when = _next_equinox_solstice(now)
    days_until = (when - now).total_seconds() / 86400.0

    # Determine current Northern-hemisphere season from the NEXT event.
    # If next is vernal_equinox  => currently winter
    # If next is summer_solstice => currently spring
    # If next is autumnal_equinox => currently summer
    # If next is winter_solstice => currently autumn
    season_lookup = {
        "vernal_equinox": "winter",
        "summer_solstice": "spring",
        "autumnal_equinox": "summer",
        "winter_solstice": "autumn",
    }
    current_season_north = season_lookup.get(name, "unknown")

    # Sun position relative to celestial equator
    if declination > 0.5:
        sun_relative = "north_of_equator"
    elif declination < -0.5:
        sun_relative = "south_of_equator"
    else:
        sun_relative = "near_equator"

    result = {
        "date": today.isoformat(),
        "current_season_northern": current_season_north,
        "next_event": {
            "name": name,
            "datetime_utc": when.isoformat(),
            "days_until": round(days_until, 2),
        },
        "sun_declination_deg": round(declination, 3),
        "sun_position": sun_relative,
        "engine": "skyfield" if _skyfield_available else "math_fallback",
    }
    _cache_set(cache_key, result, _TTL_SEASONAL)
    return result


# ── Solar Calendar (legacy, kept for backward compat) ──────────────

def _get_solar_events(year: int) -> list[tuple[str, date]]:
    """Approximate equinox/solstice dates for a given year (fallback)."""
    return [
        ("vernal_equinox", date(year, 3, 20)),
        ("summer_solstice", date(year, 6, 21)),
        ("autumnal_equinox", date(year, 9, 22)),
        ("winter_solstice", date(year, 12, 21)),
    ]


def get_solar_calendar(latitude: float) -> dict:
    """
    Hemisphere-aware season + photoperiod trend for a given latitude.
    Retained for the SunView legacy path; new code should call
    get_seasonal_marker() instead.
    """
    today = date.today()
    year = today.year
    is_southern = latitude < 0

    events = _get_solar_events(year) + _get_solar_events(year + 1)

    northern_seasons = {
        "vernal_equinox": "spring",
        "summer_solstice": "summer",
        "autumnal_equinox": "autumn",
        "winter_solstice": "winter",
    }
    southern_flip = {
        "spring": "autumn",
        "summer": "winter",
        "autumn": "spring",
        "winter": "summer",
    }

    current_season = "winter"
    next_event_name = None
    next_event_date = None
    days_until = None

    for i, (name, dt) in enumerate(events):
        if dt > today:
            next_event_name = name
            next_event_date = dt
            days_until = (dt - today).days
            if i > 0:
                prev_name = events[i - 1][0]
                current_season = northern_seasons.get(prev_name, "winter")
            else:
                current_season = "winter"
            break

    if is_southern and current_season in southern_flip:
        current_season = southern_flip[current_season]

    summer_solstice = date(year, 6, 21)
    winter_solstice = date(year, 12, 21)
    prev_winter_solstice = date(year - 1, 12, 21)

    if not is_southern:
        if prev_winter_solstice <= today < summer_solstice:
            photoperiod = "peak" if (summer_solstice - today).days <= 3 else "lengthening"
        elif summer_solstice <= today < winter_solstice:
            photoperiod = "trough" if (winter_solstice - today).days <= 3 else "shortening"
        else:
            photoperiod = "lengthening"
    else:
        if prev_winter_solstice <= today < summer_solstice:
            photoperiod = "trough" if (summer_solstice - today).days <= 3 else "shortening"
        elif summer_solstice <= today < winter_solstice:
            photoperiod = "peak" if (winter_solstice - today).days <= 3 else "lengthening"
        else:
            photoperiod = "shortening"

    return {
        "hemisphere": "southern" if is_southern else "northern",
        "current_season": current_season,
        "next_solar_event": {
            "name": next_event_name,
            "date": next_event_date.isoformat() if next_event_date else None,
            "days_until": days_until,
        },
        "photoperiod_trend": photoperiod,
        "date": today.isoformat(),
    }


# ── Solar energy mode (composite UI label) ──────────────────────────

def _derive_solar_energy_mode(
    kp_index: dict,
    xray: dict,
    aurora: dict,
    cme_alerts: list[dict],
) -> str:
    """
    Combine Kp + flare class + aurora forecast + active alerts into one of:
      quiet | unsettled | active | storm | severe
    """
    score = 0

    # Kp contribution
    kp = kp_index.get("current_kp") if isinstance(kp_index, dict) else None
    if kp is not None:
        if kp >= 8:
            score += 5
        elif kp >= 7:
            score += 4
        elif kp >= 6:
            score += 3
        elif kp >= 5:
            score += 2
        elif kp >= 4:
            score += 1

    # Flare class contribution
    flare = xray.get("flare_class") if isinstance(xray, dict) else None
    rank = _flare_class_rank(flare or "")
    if rank == 4:        # X
        score += 4
    elif rank == 3:      # M
        score += 2
    elif rank == 2:      # C
        score += 1

    # Aurora visibility forecast at moderate-to-high latitudes
    vis_now = aurora.get("visibility_now") if isinstance(aurora, dict) else None
    vis_peak = aurora.get("visibility_3day_peak") if isinstance(aurora, dict) else None
    if vis_now == "likely" or vis_peak == "likely":
        score += 1

    # Active alerts at moderate+ severity
    sev_weight = {"severe": 3, "extreme": 4, "strong": 2, "moderate": 1}
    for alert in (cme_alerts or [])[:5]:
        score += sev_weight.get(alert.get("severity"), 0)

    if score >= 9:
        return "severe"
    if score >= 6:
        return "storm"
    if score >= 3:
        return "active"
    if score >= 1:
        return "unsettled"
    return "quiet"


# ── Full Solar State composite ──────────────────────────────────────

async def get_full_solar_state(city_id: str) -> dict:
    """
    Single function the Calendar Agent and SunView call.

    Combines: sun_times + space_weather + sunspot + aurora +
    cme_alerts + schumann + seasonal_marker + derived solar_energy_mode.
    """
    city = CITY_COORDS.get(city_id)
    if city is None:
        return {"error": f"Unknown city: {city_id}", "city_id": city_id}

    sun_times_task = get_sun_times(city_id)
    space_task = get_space_weather()
    sunspot_task = get_sunspot_data()
    aurora_task = get_aurora_forecast(city_id)
    cme_task = get_cme_alerts()

    sun_times, space, sunspot, aurora, cme_alerts = await asyncio.gather(
        sun_times_task, space_task, sunspot_task, aurora_task, cme_task,
        return_exceptions=True,
    )

    def _coerce(value: Any, fallback: Any) -> Any:
        if isinstance(value, Exception):
            log.error("get_full_solar_state subtask failed: %s", value)
            return fallback
        return value

    sun_times = _coerce(sun_times, _sunrise_defaults())
    space = _coerce(space, {"kp_index": _kp_defaults(), "solar_wind": _solar_wind_defaults(),
                            "xray_flux": _xray_defaults(), "proton_flux": {"flux_pfu": None}})
    sunspot = _coerce(sunspot, {"sunspot_number": {"ssn": None}, "f10_7_flux": {"f10_7": None}})
    aurora = _coerce(aurora, {"visibility_now": "unknown", "visibility_3day_peak": "unknown",
                              "current_kp": None, "max_kp_3day": None})
    cme_alerts = _coerce(cme_alerts, [])
    if not isinstance(cme_alerts, list):
        cme_alerts = []

    schumann = get_schumann_resonance()
    seasonal = get_seasonal_marker()

    energy_mode = _derive_solar_energy_mode(
        space.get("kp_index", {}),
        space.get("xray_flux", {}),
        aurora,
        cme_alerts,
    )

    return {
        "city_id": city_id,
        "city": city["name"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "solar_energy_mode": energy_mode,
        "sun_times": sun_times,
        "space_weather": space,
        "sunspot": sunspot,
        "aurora": aurora,
        "cme_alerts": cme_alerts,
        "schumann": schumann,
        "seasonal_marker": seasonal,
    }


# ── Snapshot persistence ────────────────────────────────────────────

async def snapshot_to_disk(city_id: str = "edmonton") -> dict:
    """
    Persist a daily snapshot of get_full_solar_state to
    data/calendar/solar_snapshots.jsonl (append-only, one line per call).
    Returns the snapshot dict that was written.
    """
    state = await get_full_solar_state(city_id)
    record = {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "city_id": city_id,
        "state": state,
    }
    try:
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        with _SNAPSHOT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        log.error("Snapshot write failed: %s", exc)
        record["write_error"] = str(exc)
    return record


# ── Legacy exports (kept stable for current callers) ────────────────

async def get_solar_data(city_id: str) -> dict:
    """Legacy alias: per-city sunrise/sunset + solar calendar."""
    city = CITY_COORDS.get(city_id)
    if city is None:
        return {"error": f"Unknown city: {city_id}"}

    sunrise = await get_sun_times(city_id)
    calendar = get_solar_calendar(city["lat"])

    return {
        "city": city["name"],
        "city_id": city_id,
        "sunrise_sunset": sunrise,
        "solar_calendar": calendar,
    }


async def get_sun_dashboard(city_id: str) -> dict:
    """Legacy alias: combined per-city solar + global space weather."""
    solar_task = get_solar_data(city_id)
    space_task = get_space_weather()

    solar, space = await asyncio.gather(solar_task, space_task, return_exceptions=True)
    if isinstance(solar, Exception):
        solar = {"error": str(solar)}
    if isinstance(space, Exception):
        space = {"error": str(space)}

    return {
        "city_id": city_id,
        "solar": solar,
        "space_weather": space,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Helpers ─────────────────────────────────────────────────────────

def _safe_float(val: Any) -> Optional[float]:
    """Convert value to float, returning None on failure or 'null'."""
    if val is None:
        return None
    if isinstance(val, str) and val.strip().lower() in ("", "null", "none", "nan"):
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """Convert value to int, returning None on failure."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _reset_caches_for_tests() -> None:
    """Test-only helper: clear in-memory caches."""
    _solar_cache.clear()
    _stale_cache.clear()
