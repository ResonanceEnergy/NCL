"""
Lunar engine — moon phase calculation, energy state mapping, and cycle tracking.

Uses Skyfield for precise astronomical calculations (JPL DE421 ephemeris).
Falls back to Meeus algorithm if Skyfield unavailable.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("ncl.calendar.lunar")

# ── Try Skyfield for precise calculations ─────────────────────────────
_skyfield_available = False
_ts = None
_eph = None

try:
    from skyfield.api import load as sf_load
    from skyfield import almanac

    _data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(_data_dir, exist_ok=True)
    _ts = sf_load.timescale()
    _bsp_path = os.path.join(_data_dir, "de421.bsp")
    if os.path.exists(_bsp_path):
        _eph = sf_load(_bsp_path)
    else:
        _eph = sf_load("de421.bsp")
    _skyfield_available = True
    log.info("Skyfield loaded with DE421 ephemeris")
except Exception as e:
    log.warning("Skyfield not available, using Meeus fallback: %s", e)


# ── Phase definitions ─────────────────────────────────────────────────

PHASE_NAMES = [
    "New Moon",
    "Waxing Crescent",
    "First Quarter",
    "Waxing Gibbous",
    "Full Moon",
    "Waning Gibbous",
    "Last Quarter",
    "Waning Crescent",
]

PHASE_ICONS = {
    "New Moon": "\U0001F311",         # 🌑
    "Waxing Crescent": "\U0001F312", # 🌒
    "First Quarter": "\U0001F313",   # 🌓
    "Waxing Gibbous": "\U0001F314",  # 🌔
    "Full Moon": "\U0001F315",       # 🌕
    "Waning Gibbous": "\U0001F316",  # 🌖
    "Last Quarter": "\U0001F317",    # 🌗
    "Waning Crescent": "\U0001F318", # 🌘
}

# ── Energy state mapping ──────────────────────────────────────────────

ENERGY_PHASES = {
    "New Moon": {
        "mode": "initiate",
        "energy": "seed",
        "color": "#1A1A2E",
        "description": "Set intentions. Plant seeds. Define new thesis. Begin new positions.",
        "actions": [
            "Review and set weekly/monthly goals",
            "Define new trade thesis or research direction",
            "Plan entries for upcoming opportunities",
            "Journal intentions for this lunar cycle",
        ],
    },
    "Waxing Crescent": {
        "mode": "build",
        "energy": "emerging",
        "color": "#16213E",
        "description": "Build momentum. Execute plans. Accumulate conviction positions.",
        "actions": [
            "Execute planned entries",
            "Build position sizes gradually",
            "Follow through on research pipeline",
            "Gather supporting data for thesis",
        ],
    },
    "First Quarter": {
        "mode": "push",
        "energy": "rising",
        "color": "#0F3460",
        "description": "Push forward. Scale winners. Add to conviction. Overcome resistance.",
        "actions": [
            "Scale into winning positions",
            "Add to high-conviction trades",
            "Push through analysis backlogs",
            "Challenge assumptions with council",
        ],
    },
    "Waxing Gibbous": {
        "mode": "refine",
        "energy": "building",
        "color": "#533483",
        "description": "Refine approach. Tighten risk. Lock partial profits. Fine-tune systems.",
        "actions": [
            "Tighten stop losses on open positions",
            "Take partial profits on winners",
            "Fine-tune scanner parameters",
            "Review and adjust risk management",
        ],
    },
    "Full Moon": {
        "mode": "harvest",
        "energy": "peak",
        "color": "#E94560",
        "description": "Harvest results. Full review. Assess predictions. Peak awareness.",
        "actions": [
            "Full portfolio review and P&L assessment",
            "Score prediction accuracy for this cycle",
            "Run full council session on key positions",
            "Celebrate wins, acknowledge lessons",
        ],
    },
    "Waning Gibbous": {
        "mode": "analyze",
        "energy": "distributing",
        "color": "#7B2D8E",
        "description": "Analyze outcomes. Study what worked. Distribute knowledge. Share insights.",
        "actions": [
            "Deep analysis of trade outcomes",
            "Study signal quality metrics",
            "Update memory with learned patterns",
            "Review council recommendations vs outcomes",
        ],
    },
    "Last Quarter": {
        "mode": "release",
        "energy": "waning",
        "color": "#2C3E50",
        "description": "Release what doesn't serve. Close losers. Prune watchlist. Cut dead weight.",
        "actions": [
            "Close underperforming positions",
            "Prune stale watchlist items",
            "Clean up dead signals and predictions",
            "Memory consolidation and pruning",
        ],
    },
    "Waning Crescent": {
        "mode": "reflect",
        "energy": "resting",
        "color": "#1A1A2E",
        "description": "Reflect and rest. Journal deeply. Prepare for next cycle. Recharge.",
        "actions": [
            "Deep journal reflection on the cycle",
            "Rest from active trading if possible",
            "Prepare research agenda for new moon",
            "Review and update system configuration",
        ],
    },
}


# ── Meeus algorithm (fallback) ────────────────────────────────────────

def _meeus_phase_angle(dt: datetime) -> float:
    """
    Compute moon phase angle using Jean Meeus' simplified algorithm.
    Returns 0-360 degrees (0 = new moon, 180 = full moon).
    Accuracy: ~1 degree (~2 hours for event times).
    """
    # Julian day
    y = dt.year + (dt.month - 1) / 12.0 + (dt.day - 1) / 365.25
    jd = 367 * dt.year - int(7 * (dt.year + int((dt.month + 9) / 12)) / 4) + \
         int(275 * dt.month / 9) + dt.day + 1721013.5 + \
         (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0

    T = (jd - 2451545.0) / 36525.0  # centuries from J2000.0

    # Sun's mean anomaly (degrees)
    M = (357.5291 + 35999.0503 * T) % 360
    # Moon's mean anomaly (degrees)
    Mp = (134.9634 + 477198.8675 * T) % 360
    # Moon's mean elongation (degrees)
    D = (297.8502 + 445267.1115 * T) % 360

    D_rad = math.radians(D)
    M_rad = math.radians(M)
    Mp_rad = math.radians(Mp)

    # Phase angle with principal perturbation corrections
    phase = D \
        - 6.289 * math.sin(Mp_rad) \
        + 2.100 * math.sin(M_rad) \
        - 1.274 * math.sin(2 * D_rad - Mp_rad) \
        - 0.658 * math.sin(2 * D_rad) \
        - 0.214 * math.sin(2 * Mp_rad)

    return phase % 360


def _meeus_illumination(phase_angle: float) -> float:
    """Compute illumination fraction from phase angle."""
    return (1 - math.cos(math.radians(phase_angle))) / 2


# ── Skyfield precise calculations ────────────────────────────────────

def _skyfield_phase_angle(dt: datetime) -> float:
    """Compute precise phase angle using Skyfield/JPL ephemeris."""
    if not _skyfield_available:
        return _meeus_phase_angle(dt)

    t = _ts.utc(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    sun = _eph["sun"]
    moon = _eph["moon"]
    earth = _eph["earth"]

    e = earth.at(t)
    _, s_lon, _ = e.observe(sun).apparent().ecliptic_latlon()
    _, m_lon, _ = e.observe(moon).apparent().ecliptic_latlon()

    phase_angle = (m_lon.degrees - s_lon.degrees) % 360
    return phase_angle


def _find_major_phases(start: datetime, end: datetime) -> list[dict]:
    """
    Find exact new moon, first quarter, full moon, last quarter times
    in the given range. Returns list of {datetime, phase_id, phase_name}.
    """
    if not _skyfield_available:
        return _find_major_phases_meeus(start, end)

    t0 = _ts.utc(start.year, start.month, start.day)
    t1 = _ts.utc(end.year, end.month, end.day + 1)

    phase_func = almanac.moon_phases(_eph)
    times, phase_ids = almanac.find_discrete(t0, t1, phase_func)

    phase_id_names = {0: "New Moon", 1: "First Quarter", 2: "Full Moon", 3: "Last Quarter"}
    results = []
    for i, t in enumerate(times):
        pid = int(phase_ids[i])
        dt_utc = t.utc_datetime()
        results.append({
            "datetime": dt_utc.isoformat(),
            "timestamp": dt_utc.timestamp(),
            "phase_id": pid,
            "phase_name": phase_id_names.get(pid, f"Phase {pid}"),
            "icon": PHASE_ICONS.get(phase_id_names.get(pid, ""), ""),
        })
    return results


def _find_major_phases_meeus(start: datetime, end: datetime) -> list[dict]:
    """Fallback: find approximate major phases by scanning daily."""
    results = []
    current = start.replace(hour=0, minute=0, second=0, microsecond=0)
    prev_angle = _meeus_phase_angle(current)

    phase_targets = {
        "New Moon": 0,
        "First Quarter": 90,
        "Full Moon": 180,
        "Last Quarter": 270,
    }

    while current <= end:
        next_dt = current + timedelta(hours=6)
        curr_angle = _meeus_phase_angle(next_dt)

        for name, target in phase_targets.items():
            # Detect crossing of target angle
            if prev_angle < target <= curr_angle or \
               (prev_angle > 300 and curr_angle < 60 and target == 0):
                results.append({
                    "datetime": next_dt.isoformat(),
                    "timestamp": next_dt.timestamp(),
                    "phase_id": list(phase_targets.keys()).index(name),
                    "phase_name": name,
                    "icon": PHASE_ICONS.get(name, ""),
                })

        prev_angle = curr_angle
        current = next_dt

    return results


# ── Public API ────────────────────────────────────────────────────────

def get_moon_phase(dt: Optional[datetime] = None) -> dict:
    """
    Get current moon phase info.

    Returns:
        {
            "phase_name": "Waxing Gibbous",
            "phase_icon": "🌔",
            "phase_angle": 145.3,
            "illumination": 0.78,
            "energy": { ... },
            "days_since_new": 11,
            "days_to_full": 3,
            "days_to_new": 18,
            "cycle_progress": 0.38,  # 0-1, 0=new, 0.5=full
        }
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    if _skyfield_available:
        angle = _skyfield_phase_angle(dt)
    else:
        angle = _meeus_phase_angle(dt)

    illumination = (1 - math.cos(math.radians(angle))) / 2

    # Determine phase name from angle
    phase_idx = int((angle + 22.5) / 45.0) % 8
    phase_name = PHASE_NAMES[phase_idx]

    # Synodic month = 29.53059 days
    SYNODIC = 29.53059
    cycle_progress = angle / 360.0
    days_since_new = cycle_progress * SYNODIC
    days_to_full = ((0.5 - cycle_progress) % 1.0) * SYNODIC
    days_to_new = ((1.0 - cycle_progress) % 1.0) * SYNODIC

    energy = ENERGY_PHASES.get(phase_name, {})

    return {
        "phase_name": phase_name,
        "phase_icon": PHASE_ICONS.get(phase_name, ""),
        "phase_angle": round(angle, 2),
        "illumination": round(illumination, 4),
        "energy_mode": energy.get("mode", ""),
        "energy_state": energy.get("energy", ""),
        "energy_color": energy.get("color", ""),
        "energy_description": energy.get("description", ""),
        "suggested_actions": energy.get("actions", []),
        "days_since_new": round(days_since_new, 1),
        "days_to_full": round(days_to_full, 1),
        "days_to_new": round(days_to_new, 1),
        "cycle_progress": round(cycle_progress, 4),
        "synodic_day": round(days_since_new, 1),
        "timestamp": dt.isoformat(),
    }


def get_calendar_range(start: datetime, end: datetime) -> list[dict]:
    """
    Get daily moon phase data for a date range.
    Returns list of per-day entries with phase info.
    """
    days = []
    current = start.replace(hour=12, minute=0, second=0, microsecond=0)

    while current <= end:
        phase = get_moon_phase(current)
        phase["date"] = current.strftime("%Y-%m-%d")
        phase["weekday"] = current.strftime("%A")
        phase["weekday_short"] = current.strftime("%a")
        days.append(phase)
        current += timedelta(days=1)

    return days


def get_upcoming_major_phases(days_ahead: int = 60) -> list[dict]:
    """Find upcoming new moons, full moons, quarters in the next N days."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)
    return _find_major_phases(now, end)


def get_cycle_context() -> dict:
    """
    Get rich context about the current lunar cycle position.
    Useful for framing daily briefs, journals, and intel.
    """
    now = datetime.now(timezone.utc)
    phase = get_moon_phase(now)

    # Find next major events
    upcoming = get_upcoming_major_phases(35)
    next_new = next((p for p in upcoming if p["phase_name"] == "New Moon"), None)
    next_full = next((p for p in upcoming if p["phase_name"] == "Full Moon"), None)

    # Determine cycle half
    angle = phase["phase_angle"]
    if angle < 180:
        half = "waxing"
        half_label = "Waxing (Building)"
        half_description = "Energy is building. Focus on growth, accumulation, and forward momentum."
    else:
        half = "waning"
        half_label = "Waning (Releasing)"
        half_description = "Energy is declining. Focus on review, pruning, and preparation."

    return {
        "current_phase": phase,
        "cycle_half": half,
        "cycle_half_label": half_label,
        "cycle_half_description": half_description,
        "next_new_moon": next_new,
        "next_full_moon": next_full,
        "upcoming_phases": upcoming[:8],
        "daily_brief_frame": _build_daily_frame(phase),
    }


def _build_daily_frame(phase: dict) -> str:
    """Build a natural language framing for the daily brief."""
    name = phase["phase_name"]
    mode = phase["energy_mode"]
    days_new = phase["days_to_new"]
    days_full = phase["days_to_full"]

    if days_full <= 1:
        return f"Full Moon tonight. Peak energy. Time to harvest results and review performance."
    elif days_new <= 1:
        return f"New Moon tonight. Fresh cycle begins. Set intentions and plant seeds."
    elif phase["phase_angle"] < 180:
        return f"{name} -- {mode.title()} phase. {days_full:.0f} days to Full Moon. Energy building."
    else:
        return f"{name} -- {mode.title()} phase. {days_new:.0f} days to New Moon. Energy waning."
