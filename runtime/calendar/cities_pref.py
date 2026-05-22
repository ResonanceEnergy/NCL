"""
City preferences — default-city selection, active-cities list, timezone-aware rendering.

Edmonton, Alberta is the wired-in default. Persistent state lives in:
  - data/calendar/city_pref.json    (default city)
  - data/calendar/active_cities.json (which cities the Calendar Agent scans)

All file I/O is defensive: corrupt JSON falls back to defaults, never raises.
Writes are atomic (write to .tmp, then os.replace).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import local_events

log = logging.getLogger("ncl.calendar.cities_pref")

# ── Constants ────────────────────────────────────────────────────────
DEFAULT_CITY = "edmonton"
DEFAULT_REGION = "Alberta"
DEFAULT_COUNTRY = "Canada"
DEFAULT_TIMEZONE = "America/Edmonton"
PRIMARY_REGION_CITIES = ["edmonton", "calgary"]

# Resolve data dir relative to the repo root (runtime/calendar/cities_pref.py
# → repo_root/data/calendar).
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[2]
DATA_DIR = _REPO_ROOT / "data" / "calendar"
CITY_PREF_PATH = DATA_DIR / "city_pref.json"
ACTIVE_CITIES_PATH = DATA_DIR / "active_cities.json"


# ── Internal helpers ─────────────────────────────────────────────────
def _ensure_data_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # pragma: no cover - filesystem error
        log.warning("could not create calendar data dir %s: %s", DATA_DIR, e)


def _atomic_write_json(path: Path, payload: Any) -> bool:
    """Write JSON atomically: tmp file + os.replace. Returns True on success."""
    _ensure_data_dir()
    try:
        # Place tmp file next to the destination on the same filesystem so
        # os.replace is atomic.
        fd, tmp_path = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
            return True
        except Exception:
            # Best-effort cleanup if replace failed.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        log.warning("atomic write failed for %s: %s", path, e)
        return False


def _safe_load_json(path: Path, default: Any) -> Any:
    """Read JSON; corrupt/missing returns `default`."""
    try:
        if not path.exists():
            return default
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log.warning("could not read %s, falling back to default: %s", path, e)
        return default


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_known_city(city_id: str) -> bool:
    return isinstance(city_id, str) and city_id in local_events.CITIES


# ── Default city ─────────────────────────────────────────────────────
def get_default_city() -> str:
    """Return the persisted default city, or "edmonton" if unset/corrupt."""
    data = _safe_load_json(CITY_PREF_PATH, {})
    candidate = data.get("default") if isinstance(data, dict) else None
    if _is_known_city(candidate):
        return candidate
    return DEFAULT_CITY


def set_preferred_city(city_id: str) -> dict:
    """Persist a new default city. Returns the city metadata.

    Raises ValueError if `city_id` is not in local_events.CITIES.
    """
    if not _is_known_city(city_id):
        raise ValueError(
            f"unknown city_id: {city_id!r}. Known: {sorted(local_events.CITIES)}"
        )
    payload = {"default": city_id, "set_at": _iso_now()}
    _atomic_write_json(CITY_PREF_PATH, payload)
    return get_city_meta(city_id)


# ── Active cities list ───────────────────────────────────────────────
def _load_active_list() -> list[str]:
    raw = _safe_load_json(ACTIVE_CITIES_PATH, None)
    if not isinstance(raw, list):
        return [DEFAULT_CITY]
    # Filter to known cities only, dedupe while preserving order.
    seen: set[str] = set()
    cleaned: list[str] = []
    for c in raw:
        if _is_known_city(c) and c not in seen:
            seen.add(c)
            cleaned.append(c)
    if DEFAULT_CITY not in seen:
        cleaned.insert(0, DEFAULT_CITY)
    return cleaned or [DEFAULT_CITY]


def get_all_active_cities() -> list[str]:
    """Return the list of cities the Calendar Agent should scan.

    Default: ["edmonton"]. Edmonton is always present.
    """
    return _load_active_list()


def add_active_city(city_id: str) -> list[str]:
    """Add a city to the active list. Returns the updated list."""
    if not _is_known_city(city_id):
        raise ValueError(
            f"unknown city_id: {city_id!r}. Known: {sorted(local_events.CITIES)}"
        )
    current = _load_active_list()
    if city_id not in current:
        current.append(city_id)
    _atomic_write_json(ACTIVE_CITIES_PATH, current)
    return current


def remove_active_city(city_id: str) -> list[str]:
    """Remove a city from the active list. Edmonton cannot be removed."""
    current = _load_active_list()
    if city_id == DEFAULT_CITY:
        # Always keep edmonton — silently no-op.
        return current
    current = [c for c in current if c != city_id]
    if DEFAULT_CITY not in current:
        current.insert(0, DEFAULT_CITY)
    _atomic_write_json(ACTIVE_CITIES_PATH, current)
    return current


# ── City metadata ────────────────────────────────────────────────────
def get_city_meta(city_id: str) -> dict:
    """Return the full city metadata dict + an `is_default` bool.

    Raises ValueError if `city_id` is unknown.
    """
    if not _is_known_city(city_id):
        raise ValueError(
            f"unknown city_id: {city_id!r}. Known: {sorted(local_events.CITIES)}"
        )
    meta = dict(local_events.CITIES[city_id])
    meta["id"] = city_id
    meta["is_default"] = city_id == get_default_city()
    return meta


# ── Timezone helpers ─────────────────────────────────────────────────
def _city_tz(city_id: str) -> ZoneInfo:
    if not _is_known_city(city_id):
        raise ValueError(f"unknown city_id: {city_id!r}")
    tz_name = local_events.CITIES[city_id].get("timezone", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(tz_name)
    except Exception as e:
        log.warning(
            "ZoneInfo failed for %s (%s); falling back to %s: %s",
            city_id, tz_name, DEFAULT_TIMEZONE, e,
        )
        return ZoneInfo(DEFAULT_TIMEZONE)


def to_local_time(dt: datetime, city_id: str) -> datetime:
    """Convert `dt` to the city's local timezone.

    Naive datetimes are assumed UTC.
    """
    if not isinstance(dt, datetime):
        raise TypeError(f"expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_city_tz(city_id))


def _parse_utc(value: Any) -> datetime | None:
    """Best-effort parse of a datetime_utc field (datetime or ISO string)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            # Handle trailing Z.
            s = value.replace("Z", "+00:00") if value.endswith("Z") else value
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


def render_event_local_time(event: dict, city_id: str) -> dict:
    """Return a NEW dict with `local_time` (HH:MM) and `local_date` (YYYY-MM-DD)
    fields added based on the city's local timezone.

    If the event has no parseable `datetime_utc`, the original is shallow-copied
    and returned unchanged.
    """
    out = dict(event) if isinstance(event, dict) else {}
    utc_dt = _parse_utc(out.get("datetime_utc"))
    if utc_dt is None:
        return out
    local_dt = to_local_time(utc_dt, city_id)
    out["local_time"] = local_dt.strftime("%H:%M")
    out["local_date"] = local_dt.strftime("%Y-%m-%d")
    out["local_tz"] = local_events.CITIES[city_id].get("timezone", DEFAULT_TIMEZONE)
    return out


def render_events_localized(events: list[dict], city_id: str) -> list[dict]:
    """Map render_event_local_time over a list."""
    if not isinstance(events, list):
        return []
    return [render_event_local_time(e, city_id) for e in events]


# ── Region info ──────────────────────────────────────────────────────
def get_alberta_region_info() -> dict:
    """Return Alberta region metadata — the user's default region."""
    return {
        "region": DEFAULT_REGION,
        "country": DEFAULT_COUNTRY,
        "primary_cities": list(PRIMARY_REGION_CITIES),
        "timezone": DEFAULT_TIMEZONE,
        "default_city": DEFAULT_CITY,
    }
