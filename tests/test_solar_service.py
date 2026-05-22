"""
Tests for runtime.calendar.solar_service.

Mocks aiohttp.ClientSession to verify:
  - Parsing of NOAA SWPC and sunrise-sunset.org responses
  - TTL caching prevents re-fetch
  - Stale-cache fallback when API fails after a prior good fetch
  - Composite get_full_solar_state and snapshot_to_disk
  - Seasonal marker math-fallback path
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.calendar import solar_service


# ─── Helpers to fake aiohttp ────────────────────────────────────────

class _FakeResp:
    """Minimal stand-in for aiohttp response with json/text + status."""

    def __init__(self, *, status: int = 200, json_data=None, text_data: str = ""):
        self.status = status
        self._json = json_data
        self._text = text_data

    async def json(self, content_type=None):
        return self._json

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """
    Stand-in for aiohttp.ClientSession.

    Routes by substring match on the URL. The first matching entry wins.
    Each entry is either a _FakeResp, an Exception (to raise on entry),
    or a callable returning a _FakeResp.
    """

    def __init__(self, routes):
        self._routes = routes
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)
        for needle, response in self._routes.items():
            if needle in url:
                if isinstance(response, Exception):
                    raise response
                if callable(response):
                    return response()
                return response
        return _FakeResp(status=404, json_data={})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _clear_caches():
    """Wipe module caches between tests."""
    solar_service._reset_caches_for_tests()
    yield
    solar_service._reset_caches_for_tests()


def _install_session(monkeypatch, routes):
    """Patch aiohttp.ClientSession inside solar_service to a fake."""
    session = _FakeSession(routes)

    def _factory(*args, **kwargs):
        return session

    monkeypatch.setattr(solar_service.aiohttp, "ClientSession", _factory)
    return session


# ─── Fixture payloads ────────────────────────────────────────────────

SUNRISE_OK = {
    "status": "OK",
    "results": {
        "sunrise": "2026-05-21T11:30:00+00:00",
        "sunset": "2026-05-22T03:55:00+00:00",
        "solar_noon": "2026-05-21T19:42:00+00:00",
        "day_length": 58_500,
        "golden_hour": "2026-05-22T03:10:00+00:00",
        "civil_twilight_begin": "2026-05-21T10:50:00+00:00",
        "civil_twilight_end": "2026-05-22T04:35:00+00:00",
        "nautical_twilight_begin": "2026-05-21T09:58:00+00:00",
        "nautical_twilight_end": "2026-05-22T05:27:00+00:00",
        "astronomical_twilight_begin": "2026-05-21T08:55:00+00:00",
        "astronomical_twilight_end": "2026-05-22T06:30:00+00:00",
    },
}

KP_OK = [
    ["time_tag", "Kp", "a_running", "station_count"],
    ["2026-05-21 00:00:00", "2.33", "10", "8"],
    ["2026-05-21 03:00:00", "3.00", "12", "8"],
    ["2026-05-21 06:00:00", "5.67", "32", "8"],  # latest -> G1 storm
]

# New dict-format payload (matches current live NOAA endpoint)
KP_OK_DICT = [
    {"time_tag": "2026-05-21T00:00:00", "Kp": 2.33, "a_running": 10, "station_count": 8},
    {"time_tag": "2026-05-21T03:00:00", "Kp": 3.00, "a_running": 12, "station_count": 8},
    {"time_tag": "2026-05-21T06:00:00", "Kp": 5.67, "a_running": 32, "station_count": 8},
]

WIND_OK = [
    ["time_tag", "density", "speed", "temperature"],
    ["2026-05-21 12:00:00", "5.5", "420.1", "85000"],
    ["2026-05-21 12:05:00", "null", "null", "null"],  # gap row, should skip
    ["2026-05-21 12:10:00", "6.1", "510.7", "92000"],
]

XRAY_OK = [
    {
        "time_tag": "2026-05-21T17:00:00Z",
        "satellite": 16,
        "flux": 2.3e-6,            # C-class
        "energy": "0.1-0.8nm",
    },
    {
        "time_tag": "2026-05-21T17:01:00Z",
        "satellite": 16,
        "flux": 4.1e-8,            # short channel, should be IGNORED
        "energy": "0.05-0.4nm",
    },
]

PROTON_OK = [
    {
        "time_tag": "2026-05-21T17:00:00Z",
        "satellite": 16,
        "flux": 0.34,
        "energy": ">=10 MeV",
    },
]

OVATION_OK = {
    "Observation Time": "2026-05-21T17:00:00Z",
    "Forecast Time": "2026-05-21T17:30:00Z",
    "coordinates": [[0, 90, 5], [1, 90, 3]],  # truncated for test
}

KP_3DAY_TEXT = """:Product: 3-Day Forecast
:Issued: 2026 May 21 1230 UTC

A. NOAA Geomagnetic Activity Observation and Forecast

NOAA Kp index breakdown May 21 - May 23 2026

             May 21       May 22       May 23
00-03UT       3.00         4.00         5.00
03-06UT       3.33         4.33         5.33
06-09UT       3.00         5.00         6.00
09-12UT       2.67         4.67         5.67
12-15UT       3.00         4.00         5.00
15-18UT       3.33         4.33         5.33
18-21UT       3.00         4.00         5.00
21-00UT       3.33         4.33         5.33

Rationale: text continues here.

B. NOAA Solar Radiation Activity Observation and Forecast
"""

ALERTS_OK = [
    {
        "product_id": "K04",
        "issue_datetime": "2026-05-21 17:00:00",
        "message": "ALERT: Geomagnetic K-index of 6 (G2 Moderate storm) observed."
    },
    {
        "product_id": "FOO",
        "issue_datetime": "2026-05-21 16:00:00",
        "message": "Just a routine summary, nothing space-weather related.",
    },
    {
        "product_id": "WARN",
        "issue_datetime": "2026-05-21 18:00:00",
        "message": "WARNING: Geomagnetic Storm Watch — G3 (Strong) conditions likely.",
    },
]

SSN_OK = [
    {"time-tag": "2026-04", "ssn": "120.5", "smoothed_ssn": "118.0"},
    {"time-tag": "2026-05", "ssn": "125.7", "smoothed_ssn": "119.5"},
]

F107_OK = [{"flux": 155.2, "time_tag": "2026-05-21T20:00:00"}]
F107_OK_LEGACY = {"Flux": "155.2", "TimeStamp": "2026-05-21 18:00:00"}


# ─── Sunrise / Sun times ────────────────────────────────────────────

async def test_get_sun_times_parses_response(monkeypatch):
    _install_session(monkeypatch, {"sunrise-sunset.org": _FakeResp(json_data=SUNRISE_OK)})
    out = await solar_service.get_sun_times("edmonton", target_date=date(2026, 5, 21))
    assert out["sunrise"] == "2026-05-21T11:30:00+00:00"
    assert out["nautical_twilight_begin"] == "2026-05-21T09:58:00+00:00"
    assert out["day_length_seconds"] == 58_500
    assert out["city_id"] == "edmonton"
    assert out["city"] == "Edmonton"


async def test_get_sun_times_unknown_city():
    out = await solar_service.get_sun_times("atlantis")
    assert "error" in out


async def test_get_sun_times_cache_hit(monkeypatch):
    """A second call should not re-hit the network."""
    session = _install_session(monkeypatch, {"sunrise-sunset.org": _FakeResp(json_data=SUNRISE_OK)})
    await solar_service.get_sun_times("edmonton", target_date=date(2026, 5, 21))
    await solar_service.get_sun_times("edmonton", target_date=date(2026, 5, 21))
    assert len(session.calls) == 1


# ─── Kp index ────────────────────────────────────────────────────────

async def test_kp_index_parsing(monkeypatch):
    _install_session(monkeypatch, {"noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK)})
    out = await solar_service._fetch_kp_index()
    assert out["current_kp"] == 5.67
    assert out["storm_level"] == "G1_minor_storm"
    assert len(out["recent_entries"]) == 3


async def test_kp_index_dict_format(monkeypatch):
    """New dict-shaped NOAA payload (current live format) parses too."""
    _install_session(monkeypatch, {"noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK_DICT)})
    out = await solar_service._fetch_kp_index()
    assert out["current_kp"] == 5.67
    assert out["storm_level"] == "G1_minor_storm"


async def test_kp_index_stale_fallback(monkeypatch):
    """First call seeds stale cache; second call (with API failure) returns stale."""
    _install_session(monkeypatch, {"noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK)})
    first = await solar_service._fetch_kp_index()
    assert first["current_kp"] == 5.67

    # Invalidate TTL cache so a refetch is attempted; stale cache survives.
    solar_service._solar_cache.clear()
    _install_session(monkeypatch, {"noaa-planetary-k-index.json": _FakeResp(status=503)})
    second = await solar_service._fetch_kp_index()
    assert second.get("stale") is True
    assert second["current_kp"] == 5.67


# ─── Solar wind ──────────────────────────────────────────────────────

async def test_solar_wind_parsing_skips_null_rows(monkeypatch):
    _install_session(monkeypatch, {"plasma-1-day.json": _FakeResp(json_data=WIND_OK)})
    out = await solar_service._fetch_solar_wind()
    assert out["speed_km_s"] == 510.7
    assert out["density_p_cm3"] == 6.1
    assert out["wind_band"] == "elevated"


# ─── X-ray flux ──────────────────────────────────────────────────────

async def test_xray_parses_long_channel(monkeypatch):
    _install_session(monkeypatch, {"xrays-6-hour.json": _FakeResp(json_data=XRAY_OK)})
    out = await solar_service._fetch_xray_flux()
    assert out["flux_w_m2"] == 2.3e-6
    assert out["flare_class"] == "C"


# ─── Proton flux ─────────────────────────────────────────────────────

async def test_proton_flux_parses(monkeypatch):
    _install_session(monkeypatch, {"integral-protons-1-day.json": _FakeResp(json_data=PROTON_OK)})
    out = await solar_service._fetch_proton_flux()
    assert out["flux_pfu"] == 0.34
    assert out["alert_level"] == "none"


# ─── Sunspot + F10.7 ────────────────────────────────────────────────

async def test_sunspot_data_combines(monkeypatch):
    _install_session(monkeypatch, {
        "observed-solar-cycle-indices.json": _FakeResp(json_data=SSN_OK),
        "10cm-flux.json": _FakeResp(json_data=F107_OK),
    })
    out = await solar_service.get_sunspot_data()
    assert out["sunspot_number"]["ssn"] == 125.7
    assert out["f10_7_flux"]["f10_7"] == 155.2


async def test_f107_legacy_dict_shape(monkeypatch):
    """SWPC has shipped 10cm-flux.json as a dict in the past; we still parse it."""
    _install_session(monkeypatch, {
        "10cm-flux.json": _FakeResp(json_data=F107_OK_LEGACY),
    })
    out = await solar_service._fetch_f107_flux()
    assert out["f10_7"] == 155.2


# ─── Aurora forecast ────────────────────────────────────────────────

async def test_3day_kp_forecast_parses_text(monkeypatch):
    _install_session(monkeypatch, {"3-day-forecast.txt": _FakeResp(text_data=KP_3DAY_TEXT)})
    out = await solar_service._fetch_3day_kp_forecast()
    assert out["max_kp_3day"] == 6.0
    assert len(out["forecast"]) == 3


async def test_get_aurora_forecast_combines(monkeypatch):
    _install_session(monkeypatch, {
        "ovation_aurora_latest.json": _FakeResp(json_data=OVATION_OK),
        "3-day-forecast.txt": _FakeResp(text_data=KP_3DAY_TEXT),
        "noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK),
    })
    out = await solar_service.get_aurora_forecast("edmonton")
    assert out["city_id"] == "edmonton"
    assert out["current_kp"] == 5.67
    assert out["max_kp_3day"] == 6.0
    # Edmonton lat ~53.5 — with peak Kp=6 oval reaches ~56 deg, so "possible"
    assert out["visibility_3day_peak"] in ("likely", "possible")


async def test_aurora_visibility_low_latitude(monkeypatch):
    _install_session(monkeypatch, {
        "ovation_aurora_latest.json": _FakeResp(json_data=OVATION_OK),
        "3-day-forecast.txt": _FakeResp(text_data=KP_3DAY_TEXT),
        "noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK),
    })
    out = await solar_service.get_aurora_forecast("panama_city")
    assert out["visibility_now"] == "no"


# ─── CME / alerts ────────────────────────────────────────────────────

async def test_cme_alerts_filtering(monkeypatch):
    _install_session(monkeypatch, {"alerts.json": _FakeResp(json_data=ALERTS_OK)})
    out = await solar_service.get_cme_alerts()
    # Only the K-index and Warning ones should pass the keyword filter
    assert len(out) == 2
    severities = {a["severity"] for a in out}
    assert "moderate" in severities
    assert "strong" in severities
    # newest first
    assert out[0]["issue_datetime"] >= out[1]["issue_datetime"]


# ─── Schumann ───────────────────────────────────────────────────────

def test_schumann_baseline():
    out = solar_service.get_schumann_resonance()
    assert out["fundamental_frequency_hz"] == 7.83
    assert out["is_estimated"] is True
    assert len(out["harmonics_hz"]) == 4


# ─── Seasonal marker ────────────────────────────────────────────────

def test_seasonal_marker_math_fallback():
    """Force fallback path by temporarily disabling skyfield."""
    original = solar_service._skyfield_available
    solar_service._skyfield_available = False
    try:
        out = solar_service.get_seasonal_marker(target_date=date(2026, 5, 21))
        # May 21 -> next event should be summer_solstice
        assert out["next_event"]["name"] == "summer_solstice"
        # Sun should be north of equator
        assert out["sun_position"] == "north_of_equator"
        # Spring in Northern Hem
        assert out["current_season_northern"] == "spring"
    finally:
        solar_service._skyfield_available = original


def test_seasonal_marker_winter():
    solar_service._reset_caches_for_tests()
    original = solar_service._skyfield_available
    solar_service._skyfield_available = False
    try:
        out = solar_service.get_seasonal_marker(target_date=date(2026, 1, 15))
        assert out["next_event"]["name"] == "vernal_equinox"
        assert out["current_season_northern"] == "winter"
        assert out["sun_position"] == "south_of_equator"
    finally:
        solar_service._skyfield_available = original


# ─── Full solar state composite ────────────────────────────────────

async def test_get_full_solar_state(monkeypatch):
    routes = {
        "sunrise-sunset.org": _FakeResp(json_data=SUNRISE_OK),
        "noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK),
        "plasma-1-day.json": _FakeResp(json_data=WIND_OK),
        "xrays-6-hour.json": _FakeResp(json_data=XRAY_OK),
        "integral-protons-1-day.json": _FakeResp(json_data=PROTON_OK),
        "ovation_aurora_latest.json": _FakeResp(json_data=OVATION_OK),
        "3-day-forecast.txt": _FakeResp(text_data=KP_3DAY_TEXT),
        "alerts.json": _FakeResp(json_data=ALERTS_OK),
        "observed-solar-cycle-indices.json": _FakeResp(json_data=SSN_OK),
        "10cm-flux.json": _FakeResp(json_data=F107_OK),
    }
    _install_session(monkeypatch, routes)
    state = await solar_service.get_full_solar_state("edmonton")
    # All sections present
    for key in ("sun_times", "space_weather", "sunspot", "aurora",
                "cme_alerts", "schumann", "seasonal_marker", "solar_energy_mode"):
        assert key in state, f"missing {key}"
    # Storm conditions in our fixtures
    assert state["solar_energy_mode"] in ("active", "storm", "severe", "unsettled")
    assert state["space_weather"]["kp_index"]["current_kp"] == 5.67


# ─── Snapshot persistence ───────────────────────────────────────────

async def test_snapshot_to_disk(monkeypatch, tmp_path):
    routes = {
        "sunrise-sunset.org": _FakeResp(json_data=SUNRISE_OK),
        "noaa-planetary-k-index.json": _FakeResp(json_data=KP_OK),
        "plasma-1-day.json": _FakeResp(json_data=WIND_OK),
        "xrays-6-hour.json": _FakeResp(json_data=XRAY_OK),
        "integral-protons-1-day.json": _FakeResp(json_data=PROTON_OK),
        "ovation_aurora_latest.json": _FakeResp(json_data=OVATION_OK),
        "3-day-forecast.txt": _FakeResp(text_data=KP_3DAY_TEXT),
        "alerts.json": _FakeResp(json_data=ALERTS_OK),
        "observed-solar-cycle-indices.json": _FakeResp(json_data=SSN_OK),
        "10cm-flux.json": _FakeResp(json_data=F107_OK),
    }
    _install_session(monkeypatch, routes)

    # Redirect snapshot dir to tmp
    snap_dir = tmp_path / "calendar"
    snap_path = snap_dir / "solar_snapshots.jsonl"
    monkeypatch.setattr(solar_service, "_SNAPSHOT_DIR", snap_dir)
    monkeypatch.setattr(solar_service, "_SNAPSHOT_PATH", snap_path)

    record = await solar_service.snapshot_to_disk("edmonton")
    assert record["city_id"] == "edmonton"
    assert snap_path.exists()
    # File contains 1 JSON line
    with snap_path.open() as fh:
        lines = fh.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["city_id"] == "edmonton"
    assert "state" in parsed


# ─── Energy mode derivation ─────────────────────────────────────────

def test_solar_energy_mode_quiet():
    mode = solar_service._derive_solar_energy_mode(
        kp_index={"current_kp": 2.0},
        xray={"flare_class": "B"},
        aurora={"visibility_now": "no", "visibility_3day_peak": "no"},
        cme_alerts=[],
    )
    assert mode == "quiet"


def test_solar_energy_mode_severe():
    mode = solar_service._derive_solar_energy_mode(
        kp_index={"current_kp": 8.5},
        xray={"flare_class": "X"},
        aurora={"visibility_now": "likely", "visibility_3day_peak": "likely"},
        cme_alerts=[{"severity": "severe"}, {"severity": "extreme"}],
    )
    assert mode == "severe"


# ─── Generic helpers ────────────────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    ("3.14", 3.14),
    (2, 2.0),
    ("null", None),
    ("none", None),
    (None, None),
    ("not a number", None),
])
def test_safe_float(val, expected):
    assert solar_service._safe_float(val) == expected
