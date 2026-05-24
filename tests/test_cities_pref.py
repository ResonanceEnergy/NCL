"""Tests for runtime/calendar/cities_pref.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.calendar import cities_pref


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect cities_pref's data paths to a tmp dir so tests don't pollute prod state."""
    data_dir = tmp_path / "calendar"
    data_dir.mkdir()
    monkeypatch.setattr(cities_pref, "DATA_DIR", data_dir)
    monkeypatch.setattr(cities_pref, "CITY_PREF_PATH", data_dir / "city_pref.json")
    monkeypatch.setattr(cities_pref, "ACTIVE_CITIES_PATH", data_dir / "active_cities.json")
    return data_dir


# ── Defaults ─────────────────────────────────────────────────────────
def test_default_city_when_missing(isolated_data_dir):
    assert cities_pref.get_default_city() == "edmonton"


def test_default_active_cities_when_missing(isolated_data_dir):
    assert cities_pref.get_all_active_cities() == ["edmonton"]


def test_default_city_when_corrupt(isolated_data_dir):
    cities_pref.CITY_PREF_PATH.write_text("{not json")
    assert cities_pref.get_default_city() == "edmonton"


def test_default_city_when_unknown_value(isolated_data_dir):
    cities_pref.CITY_PREF_PATH.write_text(json.dumps({"default": "atlantis"}))
    assert cities_pref.get_default_city() == "edmonton"


def test_active_cities_corrupt_returns_default(isolated_data_dir):
    cities_pref.ACTIVE_CITIES_PATH.write_text("not json at all")
    assert cities_pref.get_all_active_cities() == ["edmonton"]


def test_alberta_region_info():
    info = cities_pref.get_alberta_region_info()
    assert info["region"] == "Alberta"
    assert info["country"] == "Canada"
    assert info["timezone"] == "America/Edmonton"
    assert info["default_city"] == "edmonton"
    assert "edmonton" in info["primary_cities"]
    assert "calgary" in info["primary_cities"]


# ── set/get round-trip ──────────────────────────────────────────────
def test_set_preferred_city_round_trip(isolated_data_dir):
    meta = cities_pref.set_preferred_city("calgary")
    assert meta["id"] == "calgary"
    assert meta["is_default"] is True
    assert cities_pref.get_default_city() == "calgary"

    # File is valid JSON and atomic-written.
    raw = json.loads(cities_pref.CITY_PREF_PATH.read_text())
    assert raw["default"] == "calgary"
    assert "set_at" in raw


def test_set_preferred_city_unknown_raises(isolated_data_dir):
    with pytest.raises(ValueError):
        cities_pref.set_preferred_city("narnia")


def test_set_preferred_city_non_string_raises(isolated_data_dir):
    with pytest.raises(ValueError):
        cities_pref.set_preferred_city(None)  # type: ignore[arg-type]


# ── Active-city management ──────────────────────────────────────────
def test_add_active_city(isolated_data_dir):
    result = cities_pref.add_active_city("calgary")
    assert "edmonton" in result
    assert "calgary" in result


def test_add_active_city_dedupes(isolated_data_dir):
    cities_pref.add_active_city("calgary")
    result = cities_pref.add_active_city("calgary")
    assert result.count("calgary") == 1


def test_add_unknown_city_raises(isolated_data_dir):
    with pytest.raises(ValueError):
        cities_pref.add_active_city("hogsmeade")


def test_remove_active_city(isolated_data_dir):
    cities_pref.add_active_city("calgary")
    cities_pref.add_active_city("oaxaca")
    result = cities_pref.remove_active_city("calgary")
    assert "calgary" not in result
    assert "oaxaca" in result
    assert "edmonton" in result


def test_remove_edmonton_is_noop(isolated_data_dir):
    cities_pref.add_active_city("calgary")
    result = cities_pref.remove_active_city("edmonton")
    assert "edmonton" in result


# ── City meta ────────────────────────────────────────────────────────
def test_get_city_meta_marks_default(isolated_data_dir):
    meta = cities_pref.get_city_meta("edmonton")
    assert meta["is_default"] is True
    assert meta["timezone"] == "America/Edmonton"
    assert meta["id"] == "edmonton"


def test_get_city_meta_non_default(isolated_data_dir):
    meta = cities_pref.get_city_meta("oaxaca")
    assert meta["is_default"] is False
    assert meta["country_name"] == "Mexico"


def test_get_city_meta_unknown_raises(isolated_data_dir):
    with pytest.raises(ValueError):
        cities_pref.get_city_meta("mordor")


# ── Timezone conversion ─────────────────────────────────────────────
def test_to_local_time_naive_treated_as_utc(isolated_data_dir):
    naive_utc_noon = datetime(2026, 5, 21, 18, 0, 0)
    local = cities_pref.to_local_time(naive_utc_noon, "edmonton")
    # Edmonton is UTC-6 in May (MDT).
    assert local.hour == 12
    assert local.tzinfo is not None


def test_to_local_time_aware_input(isolated_data_dir):
    aware = datetime(2026, 5, 21, 18, 0, 0, tzinfo=timezone.utc)
    local = cities_pref.to_local_time(aware, "edmonton")
    assert local.hour == 12


def test_utc_midnight_toronto_becomes_previous_day_edmonton(isolated_data_dir):
    """Classic timezone gotcha: 00:30 UTC May 21 is May 20 evening in Edmonton."""
    utc_just_past_midnight = datetime(2026, 5, 21, 0, 30, 0, tzinfo=timezone.utc)
    local = cities_pref.to_local_time(utc_just_past_midnight, "edmonton")
    # Edmonton MDT is UTC-6 in May → 2026-05-20 18:30.
    assert local.year == 2026
    assert local.month == 5
    assert local.day == 20
    assert local.hour == 18
    assert local.minute == 30


def test_to_local_time_unknown_city_raises(isolated_data_dir):
    with pytest.raises(ValueError):
        cities_pref.to_local_time(datetime.now(timezone.utc), "atlantis")


def test_to_local_time_non_datetime_raises(isolated_data_dir):
    with pytest.raises(TypeError):
        cities_pref.to_local_time("2026-05-21", "edmonton")  # type: ignore[arg-type]


# ── Event rendering ─────────────────────────────────────────────────
def test_render_event_local_time_with_datetime(isolated_data_dir):
    event = {
        "title": "FOMC announcement",
        "datetime_utc": datetime(2026, 5, 21, 18, 0, 0, tzinfo=timezone.utc),
    }
    rendered = cities_pref.render_event_local_time(event, "edmonton")
    assert rendered["local_time"] == "12:00"
    assert rendered["local_date"] == "2026-05-21"
    assert rendered["local_tz"] == "America/Edmonton"
    # Original event not mutated.
    assert "local_time" not in event


def test_render_event_local_time_with_iso_string(isolated_data_dir):
    event = {"title": "Test", "datetime_utc": "2026-05-21T00:30:00Z"}
    rendered = cities_pref.render_event_local_time(event, "edmonton")
    assert rendered["local_date"] == "2026-05-20"
    assert rendered["local_time"] == "18:30"


def test_render_event_local_time_no_datetime_field(isolated_data_dir):
    event = {"title": "All day", "all_day": True}
    rendered = cities_pref.render_event_local_time(event, "edmonton")
    assert rendered["title"] == "All day"
    assert "local_time" not in rendered


def test_render_event_local_time_bad_string(isolated_data_dir):
    event = {"title": "Bad", "datetime_utc": "not-a-date"}
    rendered = cities_pref.render_event_local_time(event, "edmonton")
    assert "local_time" not in rendered


def test_render_events_localized(isolated_data_dir):
    events = [
        {"title": "A", "datetime_utc": "2026-05-21T18:00:00Z"},
        {"title": "B", "datetime_utc": "2026-05-22T00:00:00Z"},
    ]
    rendered = cities_pref.render_events_localized(events, "edmonton")
    assert len(rendered) == 2
    assert rendered[0]["local_time"] == "12:00"
    assert rendered[1]["local_date"] == "2026-05-21"


def test_render_events_localized_handles_non_list(isolated_data_dir):
    assert cities_pref.render_events_localized(None, "edmonton") == []  # type: ignore[arg-type]


# ── Atomic write ─────────────────────────────────────────────────────
def test_atomic_write_leaves_no_tmp_files(isolated_data_dir):
    cities_pref.set_preferred_city("calgary")
    cities_pref.add_active_city("oaxaca")
    leftover = [p for p in isolated_data_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftover == []


def test_atomic_write_existing_file_replaced(isolated_data_dir):
    cities_pref.set_preferred_city("calgary")
    first_inode_data = cities_pref.CITY_PREF_PATH.read_text()
    cities_pref.set_preferred_city("oaxaca")
    second = cities_pref.CITY_PREF_PATH.read_text()
    assert first_inode_data != second
    assert json.loads(second)["default"] == "oaxaca"
