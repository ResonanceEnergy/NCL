"""
Tests for runtime.calendar.correlator.

Covers:
  - dedup_events: ticker-merge, source_id-merge, fuzzy-title-merge,
                  no-merge negative case, multi-rule transitive merge,
                  source-badge unioning
  - correlate_sun_moon: each of the four convergence rules
                        + a quiet-state no-flag baseline
  - escalate_alerts: every escalation rule (Kp>=7, X-flare, prediction
                     due, council overdue, FOMC today, top-5 earnings)
  - attach_correlations: end-to-end pipeline order
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.calendar.correlator import (
    attach_correlations,
    correlate_sun_moon,
    dedup_events,
    escalate_alerts,
)


NOW = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
TODAY = NOW.date().isoformat()


# ── dedup_events ────────────────────────────────────────────────────


def test_dedup_merges_on_shared_ticker_same_date():
    events = [
        {
            "id": 1,
            "date": TODAY,
            "title": "AAPL Q2 Earnings",
            "category": "earnings",
            "tickers": ["AAPL"],
            "impact": "high",
            "source": "portfolio",
        },
        {
            "id": 2,
            "date": TODAY,
            "title": "Apple Q2 Earnings Call",
            "category": "earnings",
            "tickers": ["AAPL"],
            "impact": "medium",
            "source": "market_events",
        },
    ]
    merged = dedup_events(events)
    assert len(merged) == 1
    m = merged[0]
    assert m["id"] == 1
    # Anchor (highest-impact) keeps its title.
    assert m["title"] == "AAPL Q2 Earnings"
    assert m["merged_from"] == 2
    sources = sorted(s["source"] for s in m["sources"])
    assert sources == ["market_events", "portfolio"]
    assert m["tickers"] == ["AAPL"]


def test_dedup_merges_on_source_id():
    events = [
        {"id": 11, "date": TODAY, "title": "FOMC",
         "source": "finnhub", "source_id": "fomc-2026-05-21",
         "impact": "critical"},
        {"id": 12, "date": "2026-05-22", "title": "FOMC Day-2",
         "source": "manual", "source_id": "fomc-2026-05-21",
         "impact": "medium"},
    ]
    merged = dedup_events(events)
    assert len(merged) == 1
    assert merged[0]["id"] == 11
    assert merged[0]["title"] == "FOMC"  # critical wins


def test_dedup_merges_on_fuzzy_title():
    events = [
        {"id": 21, "date": TODAY,
         "title": "Monthly Options Expiry", "source": "market",
         "impact": "high"},
        {"id": 22, "date": TODAY,
         "title": "Monthly Options Expiry", "source": "broker",
         "impact": "medium"},
    ]
    merged = dedup_events(events)
    assert len(merged) == 1
    assert merged[0]["merged_from"] == 2
    assert {s["source"] for s in merged[0]["sources"]} == {"market", "broker"}


def test_dedup_no_merge_when_dates_differ():
    events = [
        {"id": 31, "date": TODAY, "title": "AAPL Earnings",
         "tickers": ["AAPL"], "source": "a"},
        {"id": 32, "date": "2026-05-22", "title": "AAPL Earnings",
         "tickers": ["AAPL"], "source": "b"},
    ]
    merged = dedup_events(events)
    assert len(merged) == 2
    # Sources arrays still populated.
    for m in merged:
        assert len(m["sources"]) == 1


def test_dedup_no_merge_when_unrelated():
    events = [
        {"id": 41, "date": TODAY, "title": "CPI Release",
         "tickers": [], "source": "econ"},
        {"id": 42, "date": TODAY, "title": "Earnings: $TSLA",
         "tickers": ["TSLA"], "source": "broker"},
    ]
    merged = dedup_events(events)
    assert len(merged) == 2


def test_dedup_transitive_merge_via_different_rules():
    # A and B share a ticker; B and C share a source_id.
    # All three should end up in one group.
    events = [
        {"id": 51, "date": TODAY, "title": "Apple call",
         "tickers": ["AAPL"], "source": "x", "impact": "medium"},
        {"id": 52, "date": TODAY, "title": "AAPL print",
         "tickers": ["AAPL"], "source": "y", "source_id": "z-1",
         "impact": "high"},
        {"id": 53, "date": TODAY, "title": "Earnings report",
         "source": "z", "source_id": "z-1", "impact": "low"},
    ]
    merged = dedup_events(events)
    assert len(merged) == 1
    m = merged[0]
    assert m["id"] == 51  # smallest id wins
    assert m["merged_from"] == 3
    # Anchor (highest impact) title kept.
    assert m["title"] == "AAPL print"
    assert {s["source"] for s in m["sources"]} == {"x", "y", "z"}


def test_dedup_single_event_normalises_sources():
    events = [{"id": 61, "date": TODAY, "title": "Solo",
               "source": "lonely"}]
    out = dedup_events(events)
    assert out[0]["sources"] == [{"source": "lonely"}]


def test_dedup_empty():
    assert dedup_events([]) == []


# ── correlate_sun_moon ─────────────────────────────────────────────


def _solar(kp=None, flare="A", cme_alerts=0, days_until_seasonal=None):
    return {
        "kp_index": {"current_kp": kp},
        "xray_flux": {"flare_class": flare, "flux": 1e-7},
        "cme_alerts": {"alert_count": cme_alerts,
                       "alerts": [{}] * cme_alerts},
        "solar_calendar": {
            "next_solar_event": {
                "name": "summer_solstice",
                "days_until": days_until_seasonal,
            }
        },
    }


def _moon(phase="Waxing Crescent", synodic_day=None, is_perigee=False):
    return {
        "phase_name": phase,
        "synodic_day": synodic_day,
        "is_perigee": is_perigee,
    }


def test_convergence_full_moon_plus_geostorm():
    flags = correlate_sun_moon(_solar(kp=6.2), _moon(phase="Full Moon"))
    assert len(flags) == 1
    assert flags[0]["flag_type"] == "full_moon_geostorm"
    assert flags[0]["impact"] == "high"
    assert flags[0]["source"] == "cross"
    assert flags[0]["id"].startswith("cross-")


def test_convergence_new_moon_plus_xflare():
    flags = correlate_sun_moon(_solar(flare="X1.5"),
                               _moon(phase="New Moon"))
    assert any(f["flag_type"] == "new_moon_xflare" for f in flags)


def test_convergence_seasonal_pivot_disturbed():
    flags = correlate_sun_moon(_solar(kp=5.5, days_until_seasonal=0),
                               _moon(phase="First Quarter"))
    assert any(f["flag_type"] == "seasonal_pivot_disturbed" for f in flags)


def test_convergence_perigee_plus_cme():
    flags = correlate_sun_moon(_solar(cme_alerts=2),
                               _moon(synodic_day=27.5))
    assert any(f["flag_type"] == "perigee_cme" for f in flags)


def test_convergence_no_flag_quiet_state():
    flags = correlate_sun_moon(_solar(kp=2.1), _moon())
    assert flags == []


def test_convergence_ids_are_deterministic():
    a = correlate_sun_moon(_solar(kp=7), _moon(phase="Full Moon"))
    b = correlate_sun_moon(_solar(kp=7), _moon(phase="Full Moon"))
    assert [x["id"] for x in a] == [y["id"] for y in b]


def test_convergence_handles_missing_inputs():
    assert correlate_sun_moon({}, {}) == []
    assert correlate_sun_moon(None, None) == []


# ── escalate_alerts ────────────────────────────────────────────────


def test_escalate_kp_storm():
    events = [
        {"id": 1, "title": "Kp watch", "category": "solar",
         "kp": 7.5, "impact": "medium"},
        {"id": 2, "title": "Calm news", "category": "economic",
         "impact": "low"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["id"] == 1
    assert out[0]["impact"] == "critical"
    assert out[0]["priority"] == 5
    assert "escalation_reason" in out[0]
    # Non-escalated event passes through unchanged.
    assert out[1]["id"] == 2
    assert out[1]["impact"] == "low"


def test_escalate_x_flare():
    events = [
        {"id": 1, "title": "Flare alert", "category": "solar",
         "flare_class": "X2.1", "impact": "medium"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["impact"] == "critical"
    assert "X-class" in out[0]["escalation_reason"]


def test_escalate_prediction_due_soon():
    due = (NOW + timedelta(hours=3)).isoformat()
    events = [
        {"id": 1, "title": "BTC > $100k prediction",
         "category": "prediction", "due_at": due, "impact": "medium"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["impact"] == "critical"


def test_escalate_prediction_far_out_not_escalated():
    due = (NOW + timedelta(hours=24)).isoformat()
    events = [
        {"id": 1, "title": "BTC > $100k prediction",
         "category": "prediction", "due_at": due, "impact": "medium"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["impact"] == "medium"


def test_escalate_council_overdue():
    past = (NOW - timedelta(hours=2)).isoformat()
    events = [
        {"id": 1, "title": "Council: AAPL position size",
         "category": "council", "action_deadline": past,
         "impact": "high"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["impact"] == "critical"
    assert "overdue" in out[0]["escalation_reason"]


def test_escalate_fomc_today():
    events = [
        {"id": 1, "title": "FOMC Decision Day",
         "category": "fomc", "date": TODAY, "impact": "critical"},
        {"id": 2, "title": "FOMC tomorrow",
         "category": "fomc", "date": "2026-05-22", "impact": "critical"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["id"] == 1
    assert out[0]["escalation_reason"] == "FOMC today"
    # The non-today FOMC stays put (not in escalated set).
    assert out[1]["id"] == 2


def test_escalate_top5_earnings():
    events = [
        {"id": 1, "title": "Apple earnings",
         "category": "earnings", "date": TODAY,
         "tickers": ["AAPL"], "impact": "medium"},
        {"id": 2, "title": "Random small-cap",
         "category": "earnings", "date": TODAY,
         "tickers": ["XYZ"], "impact": "medium"},
    ]
    out = escalate_alerts(events, NOW)
    assert out[0]["id"] == 1
    assert out[0]["impact"] == "critical"
    assert out[1]["id"] == 2
    assert out[1]["impact"] == "medium"


def test_escalate_preserves_relative_order_for_non_escalated():
    events = [
        {"id": 1, "title": "calm a", "category": "economic"},
        {"id": 2, "title": "storm", "category": "solar", "kp": 8.0},
        {"id": 3, "title": "calm b", "category": "economic"},
    ]
    out = escalate_alerts(events, NOW)
    assert [e["id"] for e in out] == [2, 1, 3]


def test_escalate_empty():
    assert escalate_alerts([], NOW) == []


# ── attach_correlations (pipeline) ─────────────────────────────────


def test_pipeline_dedup_then_correlate_then_escalate():
    events = [
        # Duplicate pair (same ticker + date).
        {"id": 1, "date": TODAY, "title": "AAPL Earnings",
         "category": "earnings", "tickers": ["AAPL"],
         "source": "portfolio", "impact": "high"},
        {"id": 2, "date": TODAY, "title": "Apple Quarterly",
         "category": "earnings", "tickers": ["AAPL"],
         "source": "market", "impact": "medium"},
        # An unrelated quiet item.
        {"id": 3, "date": TODAY, "title": "Random econ",
         "category": "economic", "impact": "low"},
    ]
    solar = _solar(kp=7.5, flare="X1")  # triggers escalation when seen
    moon = _moon(phase="New Moon")       # + new_moon_xflare convergence

    out = attach_correlations(events, solar, moon, NOW)

    # Dedup collapses the two AAPL rows → 2 base events + 1 convergence.
    titles = [e.get("title") for e in out]
    assert any("X-class flare during new moon" in t for t in titles)
    # AAPL earnings escalated (top-5 ticker today) → must come first.
    first = out[0]
    assert first["category"] == "earnings"
    assert first["impact"] == "critical"
    # Total: 3 (deduped 2→1, kept econ, plus convergence flag).
    assert len(out) == 3


def test_pipeline_convergence_id_stable_across_runs():
    solar = _solar(kp=8.0)
    moon = _moon(phase="Full Moon")
    a = attach_correlations([], solar, moon, NOW)
    b = attach_correlations([], solar, moon, NOW)
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_pipeline_empty_inputs():
    out = attach_correlations([], {}, {}, NOW)
    assert out == []
