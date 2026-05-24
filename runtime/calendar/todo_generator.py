"""
AI-generated TO DO list builder for the NCL Calendar.

Takes a compiled list of events (from events_compiler.compile_unified_events,
built in parallel by Agent 2) plus optional solar and moon-phase context,
and produces a prioritized list of TodoItems with different specificity for
the 7-day tactical window vs the 30-day strategic window.

Pipeline:
    1. Pull cached events from events_compiler if caller did not pass any.
    2. Build a single Claude Haiku prompt that includes the events + solar/moon
       context + city + window length.
    3. Ask Haiku for a JSON list of TodoItems.
    4. If the Anthropic budget is exhausted, or the LLM call fails, fall back
       to a deterministic rule-based builder that produces one TodoItem per
       event, ordered by event impact and proximity.
    5. Stamp `energy_aligned` per item based on the current moon energy_mode.
    6. Persist the list to data/calendar/todos_{city_id}_{window}.json
       (overwritten each run) and return it.

Public API:
    generate_todos_for_window(city_id, window_days, events, solar_state, moon_phase)
    generate_7day_todos(city_id)
    generate_30day_todos(city_id)
    get_cached_todos(city_id, window)

Cost: ~0.5K input + ~0.5K output tokens per run on Claude Haiku 4.5
(~$0.001-$0.005 per run). Budget gate at $0.02 — if check_budget returns
False, we fall back to the rule-based builder so the iOS app never blocks.

DO NOT TOUCH: LaunchAgents, plists, the cost-tracker schema. Use
/opt/homebrew/bin/python3 on the host.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger("ncl.calendar.todo_generator")

# ── Constants ─────────────────────────────────────────────────────────

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
TODO_DIR = NCL_BASE / "data" / "calendar"
TODO_DIR.mkdir(parents=True, exist_ok=True)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
# (Wave 5: ANTHROPIC_ENDPOINT/_VERSION removed — runtime.llm.chat owns the wire.)

# Estimated cost ceiling per run (Haiku 4.5: ~$0.80/M input + ~$4.00/M output).
# A typical run hits ~1K input + ~1K output ≈ $0.005. We gate at $0.02 so a
# misbehaving prompt still trips the brake.
EST_COST_USD = 0.02
COST_INPUT_PER_MTOK = 0.80
COST_OUTPUT_PER_MTOK = 4.00

# Map moon energy_mode → which intent words signal alignment.
ENERGY_ALIGNMENT: dict[str, set[str]] = {
    "initiate": {
        "start",
        "open",
        "enter",
        "buy",
        "launch",
        "begin",
        "set up",
        "plan",
        "draft",
        "new",
    },
    "build": {"add", "scale", "grow", "expand", "deepen", "research", "outreach", "follow up"},
    "harvest": {
        "review",
        "audit",
        "decide",
        "rebalance",
        "harvest",
        "lock",
        "take profit",
        "trim",
        "report",
    },
    "analyze": {"analyze", "review", "audit", "decide", "compare", "evaluate", "summarize"},
    "release": {"exit", "close", "cancel", "kill", "remove", "clean", "archive", "delete"},
    "reflect": {"journal", "reflect", "reread", "summarize", "postmortem", "retro"},
    "seed": {"set", "plan", "intend", "define", "draft"},
}

VALID_URGENCIES = {"today", "this_week", "this_month"}
VALID_CATEGORIES = {
    "prediction",
    "council",
    "scanner",
    "portfolio",
    "intel",
    "journal",
    "market",
    "local",
    "moon",
    "sun",
    "cross",
}


# ── Caching helpers ───────────────────────────────────────────────────


def _cache_path(city_id: str, window: int) -> Path:
    safe = re.sub(r"[^a-z0-9_]", "_", city_id.lower())
    return TODO_DIR / f"todos_{safe}_{window}.json"


async def get_cached_todos(city_id: str, window: int) -> Optional[list[dict]]:
    """Return last persisted todo list for (city_id, window), or None."""
    path = _cache_path(city_id, window)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        if isinstance(payload, dict) and "todos" in payload:
            return payload["todos"]
        if isinstance(payload, list):
            return payload
    except Exception as e:
        log.warning("Failed to read cached todos %s: %s", path, e)
    return None


def _persist_todos(city_id: str, window: int, todos: list[dict], meta: dict | None = None) -> None:
    path = _cache_path(city_id, window)
    payload = {
        "city_id": city_id,
        "window_days": window,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(todos),
        "todos": todos,
        "meta": meta or {},
    }
    try:
        path.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        log.error("Failed to persist todos to %s: %s", path, e)


# ── Public API ────────────────────────────────────────────────────────


async def generate_todos_for_window(
    city_id: str,
    window_days: int,
    events: list[dict],
    solar_state: dict | None = None,
    moon_phase: dict | None = None,
) -> list[dict]:
    """
    Build a prioritized TodoItem list for `city_id` over `window_days`.

    Uses Claude Haiku for synthesis when the Anthropic budget allows;
    falls back to a deterministic rule-based builder otherwise.

    Returns a list of TodoItems (see module docstring for schema).
    """
    if window_days not in (7, 30):
        log.warning(
            "Non-standard window_days=%d; treating as %d-day strategic", window_days, window_days
        )

    events = events or []
    energy_mode = ""
    if moon_phase:
        energy_mode = (moon_phase.get("energy_mode") or "").lower()

    todos: list[dict] = []
    fallback_used = False
    llm_error: str | None = None

    if await _can_spend_anthropic(EST_COST_USD):
        try:
            todos = await _llm_generate_todos(
                city_id=city_id,
                window_days=window_days,
                events=events,
                solar_state=solar_state,
                moon_phase=moon_phase,
            )
        except Exception as e:
            llm_error = str(e)
            log.warning("LLM todo generation failed: %s — falling back", e)
            todos = []
    else:
        log.info("Anthropic budget gate tripped — using rule-based fallback")

    if not todos:
        fallback_used = True
        todos = _rule_based_todos(
            city_id=city_id,
            window_days=window_days,
            events=events,
            moon_phase=moon_phase,
        )

    # Post-process: stamp energy_aligned, validate, dedupe by id.
    todos = _post_process(todos, energy_mode=energy_mode, window_days=window_days)

    _persist_todos(
        city_id,
        window_days,
        todos,
        meta={
            "fallback_used": fallback_used,
            "llm_error": llm_error,
            "events_count": len(events),
            "energy_mode": energy_mode,
        },
    )
    return todos


async def generate_7day_todos(city_id: str) -> list[dict]:
    """Convenience wrapper: pull events + context, build the 7-day list."""
    return await _generate_for_default_window(city_id, 7)


async def generate_30day_todos(city_id: str) -> list[dict]:
    """Convenience wrapper: pull events + context, build the 30-day list."""
    return await _generate_for_default_window(city_id, 30)


async def _generate_for_default_window(city_id: str, window: int) -> list[dict]:
    events = await _pull_events_safe(city_id, window)
    solar_state = await _pull_solar_safe(city_id)
    moon_phase = _pull_moon_safe()
    return await generate_todos_for_window(
        city_id=city_id,
        window_days=window,
        events=events,
        solar_state=solar_state,
        moon_phase=moon_phase,
    )


# ── Optional-dependency loaders (safe even if sibling modules are absent)


async def _pull_events_safe(city_id: str, window: int) -> list[dict]:
    try:
        from . import events_compiler  # type: ignore
    except Exception:
        log.info(
            "events_compiler unavailable (Agent 2 build in progress); " "returning empty event list"
        )
        return []
    try:
        fn = getattr(events_compiler, "compile_unified_events", None)
        if fn is None:
            return []
        result = fn(city_id=city_id, window_days=window)
        if asyncio.iscoroutine(result):
            result = await result
        return list(result or [])
    except Exception as e:
        log.warning("compile_unified_events failed: %s", e)
        return []


async def _pull_solar_safe(city_id: str) -> dict | None:
    try:
        from . import solar_service  # type: ignore
    except Exception:
        return None
    # Prefer get_full_solar_state if added, else get_sun_dashboard.
    for name in ("get_full_solar_state", "get_sun_dashboard", "get_solar_data"):
        fn = getattr(solar_service, name, None)
        if fn is None:
            continue
        try:
            result = fn(city_id) if "city" in fn.__code__.co_varnames else fn()
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            log.debug("solar %s failed: %s", name, e)
    return None


def _pull_moon_safe() -> dict | None:
    try:
        from . import lunar  # type: ignore

        return lunar.get_moon_phase()
    except Exception as e:
        log.debug("lunar.get_moon_phase failed: %s", e)
        return None


# ── Anthropic budget gate ─────────────────────────────────────────────


async def _can_spend_anthropic(est_cost: float) -> bool:
    """
    Returns True if we should attempt the LLM call.

    Uses cost_tracker.check_budget when available. If the tracker import
    fails, default to True (the LLM call itself will error gracefully and
    we'll fall back to rules).
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.debug("No ANTHROPIC_API_KEY set — skipping LLM path")
        return False
    try:
        from ..cost_tracker import check_budget  # type: ignore
    except Exception:
        return True
    try:
        return await check_budget("anthropic", est_cost)
    except Exception as e:
        log.debug("check_budget failed: %s — allowing LLM call", e)
        return True


async def _record_anthropic_cost(input_tokens: int, output_tokens: int, detail: str) -> None:
    try:
        from ..cost_tracker import record_cost  # type: ignore
    except Exception:
        return
    cost_usd = (
        input_tokens * COST_INPUT_PER_MTOK + output_tokens * COST_OUTPUT_PER_MTOK
    ) / 1_000_000
    try:
        await record_cost("anthropic", cost_usd, "calendar_todo_generation", detail)
    except Exception as e:
        log.debug("record_cost failed: %s", e)


# ── LLM path ──────────────────────────────────────────────────────────


def _build_llm_prompt(
    city_id: str,
    window_days: int,
    events: list[dict],
    solar_state: dict | None,
    moon_phase: dict | None,
) -> str:
    today = date.today().isoformat()
    end = (date.today() + timedelta(days=window_days)).isoformat()

    # Trim events to keep the prompt small. 40 is plenty for either window.
    trimmed_events = events[:40]

    moon_ctx = "unknown"
    energy_mode = "unknown"
    if moon_phase:
        moon_ctx = (
            f"{moon_phase.get('phase_name', '?')} "
            f"({int((moon_phase.get('illumination') or 0) * 100)}% illum, "
            f"day {moon_phase.get('days_since_new', '?')} of cycle)"
        )
        energy_mode = (moon_phase.get("energy_mode") or "unknown").lower()

    sun_ctx = "n/a"
    if solar_state:
        kp = (solar_state.get("kp_index") or {}).get("kp")
        flux = (solar_state.get("xray_flux") or {}).get("class")
        sunrise = (solar_state.get("sunrise_sunset") or {}).get("sunrise")
        sunset = (solar_state.get("sunrise_sunset") or {}).get("sunset")
        bits = []
        if sunrise:
            bits.append(f"sunrise {sunrise}")
        if sunset:
            bits.append(f"sunset {sunset}")
        if kp is not None:
            bits.append(f"Kp={kp}")
        if flux:
            bits.append(f"X-ray={flux}")
        sun_ctx = ", ".join(bits) or "n/a"

    if window_days <= 7:
        specificity = (
            "TACTICAL 7-DAY MODE — Every action must be specific, dated "
            "(YYYY-MM-DD), and concrete. Reference exact tickers, contracts, "
            "people, or place names from the events. Prefer priority 3-5. "
            "Use imperative verbs (Review, Call, Exit, Enter, Send). Aim for "
            "8-12 todos. Each `due_date` must fall within the window. "
            "`estimated_minutes` should be realistic (5-60)."
        )
    else:
        specificity = (
            "STRATEGIC 30-DAY MODE — Actions are broader and grouped. Think "
            "themes: 'Prepare options ladder for Q2 earnings', 'Stage "
            "Polymarket alerts for markets resolving this month'. Aim for "
            "5-9 todos. `due_date` can be the deadline. Priority 2-5. "
            "`estimated_minutes` may be larger (30-180)."
        )

    schema_doc = (
        '{"id": "<stable-hash>", "priority": 1-5, "action": "<imperative>", '
        '"context": "<one-sentence why>", "due_date": "YYYY-MM-DD", '
        '"urgency": "today|this_week|this_month", '
        '"category": "prediction|council|scanner|portfolio|intel|journal|'
        'market|local|moon|sun|cross", "related_event_ids": ["<id>", ...], '
        '"energy_aligned": false, "estimated_minutes": <int>}'
    )

    return f"""You are the NCL Calendar TO DO generator. Today is {today}.
Build a prioritized action list for `{city_id}` covering {today} through {end}
({window_days} days).

CONTEXT:
- Moon: {moon_ctx}. Energy mode: {energy_mode}.
- Sun / space weather: {sun_ctx}.
- Compiled events (use these as source material — reference their `id` in
  `related_event_ids`):
{json.dumps(trimmed_events, indent=2, default=str)}

{specificity}

Return ONLY a JSON array of TodoItem objects matching this exact schema:
{schema_doc}

Hard rules:
- Output a JSON array. No prose, no markdown fences.
- Every `category` value MUST be one of: {sorted(VALID_CATEGORIES)}.
- Every `urgency` value MUST be one of: {sorted(VALID_URGENCIES)}.
- Every `due_date` MUST be between {today} and {end} inclusive.
- `related_event_ids` must reference event `id` fields from the list above,
  or be an empty array if the action is generic (e.g. moon-energy ritual).
- `energy_aligned` will be re-computed downstream; leave as false.
"""


async def _llm_generate_todos(
    city_id: str,
    window_days: int,
    events: list[dict],
    solar_state: dict | None,
    moon_phase: dict | None,
) -> list[dict]:
    """Generate todos via Claude Haiku (through runtime.llm facade).

    Migrated to ``runtime.llm.chat`` in Wave 5: the facade now owns
    retry/jitter, circuit breaker, budget gate, and cost recording.
    The legacy ``_record_anthropic_cost`` helper is kept around for
    backwards compat but is no longer invoked by the LLM path.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    prompt = _build_llm_prompt(city_id, window_days, events, solar_state, moon_phase)

    from ..llm import chat  # lazy import — keeps module load light

    result = await chat(
        model=HAIKU_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
        budget_key="anthropic",
        timeout_s=30.0,
    )
    text = result.text
    if not text:
        raise RuntimeError("Empty LLM response")

    parsed = _parse_json_array(text)
    if not isinstance(parsed, list):
        raise RuntimeError(f"LLM returned non-list: {type(parsed).__name__}")
    return parsed


def _parse_json_array(text: str) -> Any:
    """Tolerant JSON array parser — strips fences and noise."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Find the first '[' and last ']'.
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return json.loads(cleaned)  # let it raise
    return json.loads(cleaned[start : end + 1])


# ── Rule-based fallback ───────────────────────────────────────────────


def _rule_based_todos(
    city_id: str,
    window_days: int,
    events: list[dict],
    moon_phase: dict | None,
) -> list[dict]:
    """
    Deterministic builder: one todo per event, ranked by impact + proximity.

    Fires when the LLM is unavailable (budget cap, missing key, API failure)
    so the iOS app never starves for data.
    """
    out: list[dict] = []
    today = date.today()
    horizon = today + timedelta(days=window_days)

    # 1. A standing moon-energy ritual todo.
    if moon_phase:
        mode = (moon_phase.get("energy_mode") or "").lower()
        phase_name = moon_phase.get("phase_name", "moon")
        action = {
            "initiate": f"Set intentions for the new {phase_name} cycle",
            "build": f"Pick one position to scale during {phase_name}",
            "harvest": f"Review open positions before {phase_name} peak",
            "analyze": f"Audit this week's signals under {phase_name}",
            "release": f"Close one stale position during {phase_name}",
            "reflect": f"Journal lessons from this cycle ({phase_name})",
            "seed": f"Define the thesis for the next {phase_name} cycle",
        }.get(mode, f"Sit with the {phase_name} energy")
        out.append(
            {
                "id": _stable_id(f"moon::{phase_name}::{today.isoformat()}"),
                "priority": 2,
                "action": action,
                "context": (
                    moon_phase.get("energy_description") or f"Current lunar phase is {phase_name}."
                ),
                "due_date": today.isoformat(),
                "urgency": "today",
                "category": "moon",
                "related_event_ids": [],
                "energy_aligned": True,
                "estimated_minutes": 15,
            }
        )

    # 2. One todo per in-window event, ranked by source priority.
    source_priority = {
        "prediction": 5,
        "council": 5,
        "portfolio": 4,
        "scanner": 4,
        "market": 4,
        "intel": 3,
        "cross": 3,
        "journal": 2,
        "local": 2,
        "sun": 2,
        "moon": 1,
    }
    ranked = []
    for ev in events:
        ev_date = _parse_event_date(ev)
        if ev_date is None:
            continue
        if not (today <= ev_date <= horizon):
            continue
        cat = _normalize_category(ev.get("category") or ev.get("source"))
        sp = source_priority.get(cat, 2)
        ranked.append((sp, ev_date, ev, cat))

    ranked.sort(key=lambda r: (-r[0], r[1]))
    cap = 12 if window_days <= 7 else 8
    for sp, ev_date, ev, cat in ranked[:cap]:
        days_out = (ev_date - today).days
        urgency = "today" if days_out == 0 else "this_week" if days_out <= 7 else "this_month"
        title = (ev.get("title") or ev.get("name") or ev.get("label") or "Event").strip()
        action_verb = "Review" if window_days <= 7 else "Plan around"
        action = f"{action_verb} {title} ({ev_date.isoformat()})"
        out.append(
            {
                "id": _stable_id(f"event::{ev.get('id', title)}::" f"{ev_date.isoformat()}"),
                "priority": min(5, max(1, sp)),
                "action": action[:160],
                "context": (
                    ev.get("description")
                    or ev.get("summary")
                    or f"{cat.title()} event in {days_out} days."
                )[:240],
                "due_date": ev_date.isoformat(),
                "urgency": urgency,
                "category": cat,
                "related_event_ids": [str(ev.get("id"))] if ev.get("id") else [],
                "energy_aligned": False,
                "estimated_minutes": 30 if window_days <= 7 else 60,
            }
        )

    return out


def _parse_event_date(ev: dict) -> date | None:
    for key in ("date", "due_date", "start_date", "datetime", "start", "ts"):
        v = ev.get(key)
        if not v:
            continue
        try:
            if isinstance(v, date) and not isinstance(v, datetime):
                return v
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(float(v), tz=timezone.utc).date()
            s = str(v).strip()
            # ISO date or datetime
            if "T" in s:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
            return date.fromisoformat(s[:10])
        except Exception:
            continue
    return None


def _normalize_category(raw: Any) -> str:
    if not raw:
        return "intel"
    s = str(raw).strip().lower()
    if s in VALID_CATEGORIES:
        return s
    # Common aliases.
    aliases = {
        "fomc": "market",
        "cpi": "market",
        "nfp": "market",
        "ppi": "market",
        "gdp": "market",
        "earnings": "market",
        "opex": "market",
        "vix_expiry": "market",
        "futures_roll": "market",
        "fed_speech": "market",
        "economic": "market",
        "holiday": "local",
        "weather": "local",
        "ticketmaster": "local",
        "concert": "local",
        "festival": "local",
        "lunar": "moon",
        "solar": "sun",
        "kp": "sun",
        "cme": "sun",
        "trade": "portfolio",
        "position": "portfolio",
        "prediction": "prediction",
        "council": "council",
        "scanner": "scanner",
        "alert": "scanner",
    }
    return aliases.get(s, "intel")


def _stable_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


# ── Post-processing ──────────────────────────────────────────────────


def _post_process(todos: list[dict], energy_mode: str, window_days: int) -> list[dict]:
    today = date.today()
    horizon = today + timedelta(days=window_days)
    seen_ids: set[str] = set()
    out: list[dict] = []
    energy_words = ENERGY_ALIGNMENT.get(energy_mode, set())

    for raw in todos:
        if not isinstance(raw, dict):
            continue
        try:
            item = _coerce_item(raw, today=today, horizon=horizon)
        except Exception as e:
            log.debug("Dropping malformed todo %r: %s", raw, e)
            continue

        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])

        action_l = item["action"].lower()
        item["energy_aligned"] = any(w in action_l for w in energy_words)

        out.append(item)

    # Sort: priority desc, then due_date asc.
    out.sort(key=lambda t: (-t["priority"], t["due_date"]))
    return out


def _coerce_item(raw: dict, today: date, horizon: date) -> dict:
    action = str(raw.get("action") or "").strip()
    if not action:
        raise ValueError("missing action")

    try:
        priority = int(raw.get("priority", 3))
    except Exception:
        priority = 3
    priority = max(1, min(5, priority))

    due_raw = raw.get("due_date") or today.isoformat()
    try:
        due = date.fromisoformat(str(due_raw)[:10])
    except Exception:
        due = today
    if due < today:
        due = today
    if due > horizon:
        due = horizon
    due_iso = due.isoformat()

    urgency = str(raw.get("urgency") or "").lower().strip()
    if urgency not in VALID_URGENCIES:
        days_out = (due - today).days
        urgency = "today" if days_out <= 0 else "this_week" if days_out <= 7 else "this_month"

    category = _normalize_category(raw.get("category"))

    related = raw.get("related_event_ids") or []
    if not isinstance(related, list):
        related = [str(related)]
    related = [str(r) for r in related if r is not None][:10]

    try:
        est = int(raw.get("estimated_minutes", 30))
    except Exception:
        est = 30
    est = max(1, min(480, est))

    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        item_id = _stable_id(f"{action}::{due_iso}::{category}")

    return {
        "id": item_id,
        "priority": priority,
        "action": action[:200],
        "context": str(raw.get("context") or "")[:300],
        "due_date": due_iso,
        "urgency": urgency,
        "category": category,
        "related_event_ids": related,
        "energy_aligned": bool(raw.get("energy_aligned", False)),
        "estimated_minutes": est,
    }
