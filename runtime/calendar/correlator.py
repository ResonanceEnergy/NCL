"""
Calendar correlator — dedup, sun/moon convergence, and alert escalation.

Handles three problems that arise once events flow into the unified calendar
from multiple sources (market events, portfolio earnings, predictions,
council decisions, scanner hits, solar/lunar feeds):

  1. Dedup     — collapse rows that describe the same underlying event.
  2. Cross-correlation — emit ``cross``-sourced "convergence flags" when
                          lunar + space-weather conditions line up in
                          historically noteworthy ways.
  3. Escalation — promote time-critical items (X-class flare, prediction
                  due, overdue council decision, etc.) to the top of the
                  list regardless of normal sort.

Public surface (called by the Calendar Agent):

    dedup_events(events)
    correlate_sun_moon(solar_state, moon_phase)
    escalate_alerts(events, now)
    attach_correlations(events, solar_state, moon_phase, now)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any


log = logging.getLogger("ncl.calendar.correlator")

# ── Constants ────────────────────────────────────────────────────────

# Order matters: higher index = higher impact when picking the "winning"
# event title/description during a merge.
_IMPACT_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

# Fuzzy title-match threshold used by dedup_events.
_TITLE_SIM_THRESHOLD = 0.85

# Used by escalate_alerts.
_PREDICTION_DUE_WINDOW = timedelta(hours=6)

# Top portfolio tickers that get a priority bump on earnings day.
# Kept here (rather than yanked from /portfolio at call time) so the
# function stays pure and unit-testable. The Calendar Agent can pass
# a custom list via the events themselves (event["is_top_position"]).
_DEFAULT_TOP_POSITIONS = {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"}


# ── Helpers ──────────────────────────────────────────────────────────


def _impact_rank(event: dict) -> int:
    return _IMPACT_RANK.get((event.get("impact") or "low").lower(), 0)


def _norm_title(s: str) -> str:
    return " ".join((s or "").lower().split())


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


def _as_set(value: Any) -> set:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {v for v in value if v is not None}
    return {value}


def _event_id(event: dict) -> Any:
    """Return a stable id for an event. Falls back to (date, title)."""
    eid = event.get("id")
    if eid is not None:
        return eid
    return (event.get("date"), event.get("title"))


def _ids_min(events: list[dict]) -> Any:
    """Pick the smallest id from a merge group for deterministic output."""
    ids = [e.get("id") for e in events if e.get("id") is not None]
    if not ids:
        # Synthesize a stable id from the (sorted) constituent identifiers.
        keys = sorted(str(_event_id(e)) for e in events)
        return hashlib.sha1("|".join(keys).encode()).hexdigest()[:12]
    try:
        return min(ids)
    except TypeError:
        # Mixed types — fall back to string comparison.
        return min(str(i) for i in ids)


def _parse_event_date(value: Any) -> datetime | None:
    """Best-effort parser for the ``date`` field on an event."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _date_key(event: dict) -> str:
    """The bucket key used for date-equality matching."""
    raw = event.get("date") or ""
    if isinstance(raw, str) and len(raw) >= 10:
        return raw[:10]
    dt = _parse_event_date(raw)
    return dt.date().isoformat() if dt else ""


# ── Dedup ────────────────────────────────────────────────────────────


def dedup_events(events: list[dict]) -> list[dict]:
    """
    Merge events that share entity overlap and the same calendar date.

    Matching rules (any one triggers a merge):
      1. Same ticker in ``tickers`` list AND same date
      2. Same ``source_id`` (already-deduped upstream)
      3. Title cosine-style similarity >= 0.85 AND same date

    The merged event keeps the highest-impact constituent's title and
    description, unions ``tickers`` / ``entities`` / ``urls``, and
    appends every original ``source`` (with its ``source_id``) into a
    new ``sources`` list. The merged event's id is the smallest id from
    the merge group (deterministic).
    """
    if not events:
        return []

    n = len(events)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Lower index becomes root so deterministic ordering survives.
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    # --- rule 2: same source_id (cheap O(n)) ---
    by_source_id: dict[Any, int] = {}
    for i, ev in enumerate(events):
        sid = ev.get("source_id")
        if sid is None:
            continue
        if sid in by_source_id:
            union(by_source_id[sid], i)
            log.debug("dedup: merging on source_id=%s (rows %d,%d)", sid, by_source_id[sid], i)
        else:
            by_source_id[sid] = i

    # Bucket by date so the O(n^2) rules stay small.
    by_date: dict[str, list[int]] = {}
    for i, ev in enumerate(events):
        by_date.setdefault(_date_key(ev), []).append(i)

    # --- rules 1 & 3: per-date bucket comparisons ---
    for dkey, indices in by_date.items():
        if not dkey or len(indices) < 2:
            continue
        for a_pos, i in enumerate(indices):
            ev_i = events[i]
            tickers_i = _as_set(ev_i.get("tickers"))
            title_i = ev_i.get("title", "")
            for j in indices[a_pos + 1 :]:
                if find(i) == find(j):
                    continue
                ev_j = events[j]
                # rule 1 — shared ticker
                tickers_j = _as_set(ev_j.get("tickers"))
                if tickers_i and tickers_j and tickers_i & tickers_j:
                    union(i, j)
                    log.debug(
                        "dedup: ticker overlap %s on %s (rows %d,%d)",
                        tickers_i & tickers_j,
                        dkey,
                        i,
                        j,
                    )
                    continue
                # rule 3 — fuzzy title
                sim = _title_similarity(title_i, ev_j.get("title", ""))
                if sim >= _TITLE_SIM_THRESHOLD:
                    union(i, j)
                    log.debug("dedup: title sim=%.2f on %s (rows %d,%d)", sim, dkey, i, j)

    # Collect groups in original order.
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    merged: list[dict] = []
    for root in sorted(groups.keys()):
        members = [events[k] for k in groups[root]]
        merged.append(_merge_group(members))
    return merged


def _merge_group(members: list[dict]) -> dict:
    """Combine a merge group into one event."""
    if len(members) == 1:
        ev = dict(members[0])
        # Normalise: always expose a "sources" array.
        if "sources" not in ev:
            src = ev.get("source")
            sid = ev.get("source_id")
            badge = {"source": src} if src else {}
            if sid is not None:
                badge["source_id"] = sid
            ev["sources"] = [badge] if badge else []
        return ev

    # Pick the highest-impact member as the "anchor" for title/description.
    # Ties broken by category priority, then by original order (stable).
    def _anchor_key(e: dict) -> tuple:
        return (
            -_impact_rank(e),
            -int(e.get("priority", 0) or 0),
        )

    anchor = sorted(members, key=_anchor_key)[0]

    tickers: set = set()
    entities: set = set()
    urls: set = set()
    sources: list[dict] = []
    seen_source_keys: set = set()
    related_ids: list = []

    for ev in members:
        tickers |= _as_set(ev.get("tickers"))
        entities |= _as_set(ev.get("entities"))
        for u in _as_set(ev.get("urls")) | ({ev.get("url")} if ev.get("url") else set()):
            urls.add(u)
        eid = ev.get("id")
        if eid is not None:
            related_ids.append(eid)

        # Build a source badge per constituent (preserve duplicates only
        # when their source_id differs).
        src = ev.get("source") or ev.get("category") or "unknown"
        sid = ev.get("source_id")
        key = (src, sid)
        if key in seen_source_keys:
            continue
        seen_source_keys.add(key)
        badge: dict = {"source": src}
        if sid is not None:
            badge["source_id"] = sid
        if ev.get("impact"):
            badge["impact"] = ev["impact"]
        sources.append(badge)

    merged = dict(anchor)
    merged["id"] = _ids_min(members)
    merged["sources"] = sources
    if tickers:
        merged["tickers"] = sorted(tickers)
    if entities:
        merged["entities"] = sorted(entities)
    if urls:
        merged["urls"] = sorted(urls)
    if related_ids:
        merged["related_ids"] = sorted(related_ids, key=str)
    merged["merged_from"] = len(members)
    log.debug(
        "dedup: merged %d events into id=%s (%s)", len(members), merged["id"], merged.get("title")
    )
    return merged


# ── Sun/Moon Convergence ─────────────────────────────────────────────


def _convergence_id(date_str: str, flag_type: str) -> str:
    """Deterministic id so re-runs don't duplicate convergence flags."""
    raw = f"{date_str}|{flag_type}"
    return "cross-" + hashlib.sha1(raw.encode()).hexdigest()[:10]


def _flare_class_starts_with(xray: dict | None, letter: str) -> bool:
    if not xray:
        return False
    fc = (xray.get("flare_class") or "").upper()
    return fc.startswith(letter.upper())


def correlate_sun_moon(solar_state: dict, moon_phase: dict) -> list[dict]:
    """
    Emit ``source="cross"`` convergence-flag events when notable
    sun/moon alignments occur.

    Supported flags:
      - Full moon + Kp >= 5 → "Geomagnetic storm during full moon"
      - New moon + X-class flare → "X-class flare during new moon"
      - Solstice/equinox + Kp >= 5 → "Seasonal pivot under disturbed conditions"
      - Lunar perigee + CME alert → "Perigee + CME convergence"

    All emitted events use the standard schema (date/title/description/
    impact/source/category/priority/id).
    """
    if not solar_state or not moon_phase:
        return []

    today = datetime.now(timezone.utc).date().isoformat()
    flags: list[dict] = []

    # Pull commonly-used fields once.
    # Be defensive about schema: Agent 1's solar_service.get_full_solar_state
    # nests kp_index/xray_flux/proton_flux under "space_weather", emits
    # cme_alerts as a flat list, and surfaces seasonal under "seasonal_marker".
    # Older callers may pass flat layouts. Read from either.
    phase_name = (moon_phase.get("phase_name") or "").strip()

    sw = solar_state.get("space_weather") or {}
    kp_block = solar_state.get("kp_index") or sw.get("kp_index") or {}
    current_kp = kp_block.get("current_kp") if isinstance(kp_block, dict) else None
    try:
        current_kp = float(current_kp) if current_kp is not None else None
    except (TypeError, ValueError):
        current_kp = None

    xray = solar_state.get("xray_flux") or sw.get("xray_flux") or {}
    if not isinstance(xray, dict):
        xray = {}

    cme_raw = solar_state.get("cme_alerts")
    if isinstance(cme_raw, list):
        cme_count = len(cme_raw)
    elif isinstance(cme_raw, dict):
        cme_count = int(cme_raw.get("alert_count") or len(cme_raw.get("alerts") or []))
    else:
        cme_count = int(solar_state.get("cme_alerts_count") or 0)

    # --- Full moon + Kp >= 5 ---
    if phase_name == "Full Moon" and current_kp is not None and current_kp >= 5:
        flags.append(
            {
                "id": _convergence_id(today, "full_moon_geostorm"),
                "date": today,
                "title": "Geomagnetic storm during full moon",
                "description": (
                    f"Full Moon coincides with Kp={current_kp:.1f} "
                    "(active geomagnetic conditions). Heightened market "
                    "and biological volatility historically observed."
                ),
                "category": "cross",
                "impact": "high",
                "priority": 4,
                "source": "cross",
                "all_day": True,
                "flag_type": "full_moon_geostorm",
                "metrics": {"kp": current_kp, "phase": phase_name},
            }
        )

    # --- New moon + X-class flare ---
    if phase_name == "New Moon" and _flare_class_starts_with(xray, "X"):
        flags.append(
            {
                "id": _convergence_id(today, "new_moon_xflare"),
                "date": today,
                "title": "X-class flare during new moon",
                "description": (
                    f"New Moon coincides with X-class solar flare "
                    f"(flux={xray.get('flux')}). Reset-energy phase under "
                    "extreme solar forcing — re-anchor intentions."
                ),
                "category": "cross",
                "impact": "high",
                "priority": 4,
                "source": "cross",
                "all_day": True,
                "flag_type": "new_moon_xflare",
                "metrics": {
                    "flare_class": xray.get("flare_class"),
                    "phase": phase_name,
                },
            }
        )

    # --- Solstice / equinox + disturbed geomag ---
    # Agent 1 uses "seasonal_marker" with "next_event"; legacy used "solar_calendar"
    # with "next_solar_event". Accept either.
    seasonal = solar_state.get("seasonal_marker") or solar_state.get("solar_calendar") or {}
    if not isinstance(seasonal, dict):
        seasonal = {}
    next_event = seasonal.get("next_event") or seasonal.get("next_solar_event") or {}
    if not isinstance(next_event, dict):
        next_event = {}
    days_until = next_event.get("days_until")
    if days_until is not None and days_until <= 1 and current_kp is not None and current_kp >= 5:
        flags.append(
            {
                "id": _convergence_id(today, "seasonal_pivot_disturbed"),
                "date": today,
                "title": "Seasonal pivot under disturbed conditions",
                "description": (
                    f"{next_event.get('name','seasonal pivot')} in "
                    f"{days_until} day(s) with Kp={current_kp:.1f}. "
                    "Liminal window — expect emotional and market noise."
                ),
                "category": "cross",
                "impact": "medium",
                "priority": 3,
                "source": "cross",
                "all_day": True,
                "flag_type": "seasonal_pivot_disturbed",
                "metrics": {
                    "kp": current_kp,
                    "event": next_event.get("name"),
                    "days_until": days_until,
                },
            }
        )

    # --- Perigee + CME ---
    # We accept either an explicit ``is_perigee`` flag on moon_phase
    # (preferred — Skyfield perigee detection) or fall back to the
    # synodic_day approximation (~+/-1d of synodic day 27.5).
    is_perigee = bool(moon_phase.get("is_perigee"))
    if not is_perigee:
        synodic = moon_phase.get("synodic_day")
        if isinstance(synodic, (int, float)) and 26.5 <= synodic <= 28.5:
            is_perigee = True
    if is_perigee and cme_count > 0:
        flags.append(
            {
                "id": _convergence_id(today, "perigee_cme"),
                "date": today,
                "title": "Perigee + CME convergence",
                "description": (
                    f"Lunar perigee with {cme_count} active CME alert(s). "
                    "Gravitational and electromagnetic forcing align — "
                    "raise risk awareness across positions."
                ),
                "category": "cross",
                "impact": "high",
                "priority": 4,
                "source": "cross",
                "all_day": True,
                "flag_type": "perigee_cme",
                "metrics": {"cme_alerts": cme_count, "phase": phase_name},
            }
        )

    if flags:
        log.info(
            "correlate_sun_moon: emitted %d convergence flag(s): %s",
            len(flags),
            [f["flag_type"] for f in flags],
        )
    return flags


# ── Escalation ───────────────────────────────────────────────────────


def _should_escalate(event: dict, now: datetime) -> tuple[bool, str]:
    """Return (escalate?, reason)."""
    cat = (event.get("category") or "").lower()
    src = (event.get("source") or "").lower()
    today_iso = now.date().isoformat()

    # Solar event with Kp >= 7 or X-class flare.
    if (
        cat == "solar"
        or src in {"solar", "swpc", "noaa"}
        or event.get("flag_type", "").startswith("full_moon")
        or event.get("flag_type", "").startswith("new_moon")
    ):
        kp = event.get("kp")
        if kp is None:
            metrics = event.get("metrics") or {}
            kp = metrics.get("kp")
        try:
            kp_val = float(kp) if kp is not None else None
        except (TypeError, ValueError):
            kp_val = None
        if kp_val is not None and kp_val >= 7:
            return True, f"kp>=7 ({kp_val})"

        flare = event.get("flare_class") or (event.get("metrics") or {}).get("flare_class") or ""
        if isinstance(flare, str) and flare.upper().startswith("X"):
            return True, f"X-class flare ({flare})"

    # Prediction due within next 6h.
    if cat == "prediction" or src == "prediction":
        due = event.get("due_at") or event.get("deadline") or event.get("predicted_at")
        due_dt = _parse_event_date(due)
        if due_dt is not None:
            delta = due_dt - now
            if timedelta(0) <= delta <= _PREDICTION_DUE_WINDOW:
                return True, f"prediction due in {delta}"

    # Council decision with action_deadline in the past.
    if cat == "council" or src == "council":
        deadline = event.get("action_deadline") or event.get("deadline")
        ddt = _parse_event_date(deadline)
        if ddt is not None and ddt < now:
            return True, f"council action_deadline overdue ({deadline})"

    # FOMC market event happening today.
    if cat == "fomc" and _date_key(event) == today_iso:
        return True, "FOMC today"

    # Portfolio earnings for top-5 positions today.
    if cat == "earnings" and _date_key(event) == today_iso:
        if event.get("is_top_position"):
            return True, "top-5 position earnings today"
        tickers = _as_set(event.get("tickers"))
        if tickers & _DEFAULT_TOP_POSITIONS:
            return True, f"top-5 ticker earnings today ({tickers & _DEFAULT_TOP_POSITIONS})"

    return False, ""


def escalate_alerts(events: list[dict], now: datetime) -> list[dict]:
    """
    Reorder ``events`` so anything matching escalation rules sits at
    the top of the list AND has its ``impact`` bumped to ``critical``
    and its ``priority`` set to 5.

    The original list is not mutated; new dicts are returned for
    escalated rows. Non-escalated rows are returned as-is, preserving
    their original relative order behind the escalated rows.
    """
    if not events:
        return []

    escalated: list[dict] = []
    rest: list[dict] = []
    for ev in events:
        ok, reason = _should_escalate(ev, now)
        if ok:
            new_ev = dict(ev)
            new_ev["impact"] = "critical"
            new_ev["priority"] = 5
            new_ev["escalation_reason"] = reason
            log.info(
                "escalate_alerts: %s -> critical (%s)", ev.get("title") or ev.get("id"), reason
            )
            escalated.append(new_ev)
        else:
            rest.append(ev)
    return escalated + rest


# ── Pipeline ─────────────────────────────────────────────────────────


def attach_correlations(
    events: list[dict],
    solar_state: dict,
    moon_phase: dict,
    now: datetime,
) -> list[dict]:
    """
    Single entry-point for the Calendar Agent. Runs the full pipeline:

        dedup_events(events)
        -> appends correlate_sun_moon(...) flags
        -> escalate_alerts(merged, now)
    """
    deduped = dedup_events(events or [])
    convergences = correlate_sun_moon(solar_state or {}, moon_phase or {})

    # Convergence flags are independent identities — they pass through
    # dedup if they share a deterministic id with an existing entry.
    if convergences:
        seen = {e.get("id") for e in deduped if e.get("id") is not None}
        for c in convergences:
            if c.get("id") not in seen:
                deduped.append(c)

    return escalate_alerts(deduped, now)
