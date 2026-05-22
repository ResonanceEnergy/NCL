"""
NCL Calendar Agent
==================

Autonomous orchestrator that ties together all calendar subsystems built by
the swarm:

  Agent 1 — solar_service        (solar/space weather state, snapshots)
  Agent 2 — events_compiler      (unified market + local + custom events)
  Agent 3 — todo_generator       (LLM-backed todo synthesis)
  Agent 4 — correlator           (cross-link events ↔ moon ↔ solar ↔ signals)
  Agent 8 — cities_pref          (default + active cities)
  Existing — lunar.py             (moon phase, cycle context)

The agent runs in the Brain scheduler on a 15-minute cadence (scan_cycle())
and exposes cache-first read APIs (compile_events, get_todos, get_sun_state)
for the iOS client + FastAPI routes.

Cost discipline
---------------
The TODO generator is the only paid step. We skip regeneration if the most
recent cache is < 30 min old AND the event id set hasn't changed. This keeps
daily LLM spend under ~$0.20 per active city.

Persistence
-----------
  data/calendar/agent_state.json   — last_scan_at, cycle_count, errors[]
  data/calendar/events/            — per-city / per-window cached compiles
  data/calendar/todos/             — per-city / per-window cached todos
  data/calendar/sun/               — per-city sun snapshots (Agent 1 handles)

Robust against missing dependency modules — every import is wrapped in
try/except ImportError and degraded gracefully with a logged warning.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("ncl.calendar.agent")


# ── Lazy / optional imports ──────────────────────────────────────────
# Each subsystem is imported in a guarded helper so the agent still runs
# when an upstream module hasn't been merged yet.

def _try_import(label: str, fn: Callable[[], Any]) -> Optional[Any]:
    """Run an import callable, swallow ImportError, log + return None."""
    try:
        return fn()
    except ImportError as e:
        log.warning("[CALENDAR-AGENT] module %s unavailable: %s", label, e)
        return None
    except Exception as e:  # noqa: BLE001 — defensive
        log.warning("[CALENDAR-AGENT] module %s import failed: %s", label, e)
        return None


def _load_modules() -> dict[str, Any]:
    """
    Import every dependency module under try/except so we can run without
    them. Returns a dict keyed by short name; missing keys are absent or
    explicitly None.
    """
    mods: dict[str, Any] = {}

    def _imp_solar():
        from . import solar_service  # type: ignore
        return solar_service
    mods["solar"] = _try_import("solar_service", _imp_solar)

    def _imp_events():
        from . import events_compiler  # type: ignore
        return events_compiler
    mods["events_compiler"] = _try_import("events_compiler", _imp_events)

    def _imp_todos():
        from . import todo_generator  # type: ignore
        return todo_generator
    mods["todo_generator"] = _try_import("todo_generator", _imp_todos)

    def _imp_corr():
        from . import correlator  # type: ignore
        return correlator
    mods["correlator"] = _try_import("correlator", _imp_corr)

    def _imp_cities():
        from . import cities_pref  # type: ignore
        return cities_pref
    mods["cities_pref"] = _try_import("cities_pref", _imp_cities)

    def _imp_lunar():
        from . import lunar  # type: ignore
        return lunar
    mods["lunar"] = _try_import("lunar", _imp_lunar)

    return mods


# ── Constants ────────────────────────────────────────────────────────

SCAN_INTERVAL_S = 15 * 60         # 15 minutes between scan_cycle passes
TODO_CACHE_MIN_AGE_S = 30 * 60    # only regen TODOs if cache > 30 min old
EVENT_CACHE_MAX_AGE_S = 15 * 60   # events cache is fresh for 15 min
SUN_CACHE_MAX_AGE_S = 15 * 60     # sun snapshot cache freshness
DEFAULT_CITIES = ["edmonton"]
DEFAULT_WINDOWS = [7, 30]


# ── Helpers ──────────────────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_run_maybe_async(value: Any) -> Awaitable[Any]:
    """
    Turn either a coroutine or a plain value into an awaitable. Lets us
    call the same path whether a dependency is async or sync.
    """
    if asyncio.iscoroutine(value):
        return value

    async def _wrap() -> Any:
        return value
    return _wrap()


async def _maybe_await(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call fn, await if it returned a coroutine."""
    out = fn(*args, **kwargs)
    if asyncio.iscoroutine(out):
        return await out
    return out


async def _call_with_compat(
    fn: Callable[..., Any],
    kwargs_options: list[dict] | None = None,
    positional_options: list[tuple] | None = None,
) -> Any:
    """
    Call fn with the first set of kwargs (or positional args) that match
    its signature. Swarm modules may use slightly different signatures; we
    try each option in order. Raises the last TypeError if every option
    fails — lets the caller surface a real signature mismatch.
    """
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
    except (TypeError, ValueError):
        sig = None
        params = {}

    # Try kwargs options first — prune unknown kwargs when signature is known
    if kwargs_options:
        for kw in kwargs_options:
            try:
                if sig is not None and not any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
                ):
                    kw_filtered = {k: v for k, v in kw.items() if k in params}
                    # If the filter dropped a required-looking key, prefer the original
                    # so we get a useful TypeError instead of a silent wrong-call.
                    if not kw_filtered:
                        continue
                    return await _maybe_await(fn, **kw_filtered)
                return await _maybe_await(fn, **kw)
            except TypeError:
                continue

    if positional_options:
        last_exc: Optional[Exception] = None
        for args in positional_options:
            try:
                return await _maybe_await(fn, *args)
            except TypeError as e:
                last_exc = e
                continue
        if last_exc is not None:
            raise last_exc

    raise TypeError(f"No compatible call signature for {getattr(fn, '__name__', fn)}")


def _event_id_set(events: list[dict] | None) -> frozenset[str]:
    """Build a deterministic id-set used for change-detection."""
    if not events:
        return frozenset()
    ids: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        eid = (
            ev.get("id")
            or ev.get("event_id")
            or ev.get("uid")
            or f"{ev.get('source','?')}::{ev.get('title','?')}::{ev.get('date','?')}"
        )
        ids.append(str(eid))
    return frozenset(ids)


# ── Calendar Agent ───────────────────────────────────────────────────

class CalendarAgent:
    """
    Autonomous orchestrator for the calendar subsystem.

    Lifecycle:
      - constructed by the singleton accessor (or directly in tests)
      - scheduler awaits .run() — which loops scan_cycle() every 15 min
      - iOS / FastAPI routes call cache-first read methods
    """

    def __init__(self, brain: Any = None, data_dir: Optional[str | Path] = None) -> None:
        self.brain = brain
        self._stop = False
        self._modules = _load_modules()
        self._modules_loaded = [k for k, v in self._modules.items() if v is not None]

        # Resolve data_dir: explicit arg > brain.config.data_dir > project default
        if data_dir is not None:
            self.data_dir = Path(data_dir).expanduser()
        else:
            try:
                cfg_dir = getattr(getattr(brain, "config", None), "data_dir", None)
            except Exception:
                cfg_dir = None
            if cfg_dir:
                self.data_dir = Path(cfg_dir).expanduser()
            else:
                # Project default — runtime/calendar/calendar_agent.py → ../../data
                self.data_dir = (Path(__file__).resolve().parents[2] / "data").resolve()

        self.calendar_dir = self.data_dir / "calendar"
        self.events_dir = self.calendar_dir / "events"
        self.todos_dir = self.calendar_dir / "todos"
        for d in (self.calendar_dir, self.events_dir, self.todos_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.state_path = self.calendar_dir / "agent_state.json"

        # In-memory caches (cache-first read APIs use these)
        # Key: (city_id, window) → {"ts": float, "events": [...], "event_ids": frozenset}
        self._events_cache: dict[tuple[str, int], dict[str, Any]] = {}
        # Key: (city_id, window) → {"ts": float, "todos": [...], "source_event_ids": frozenset}
        self._todos_cache: dict[tuple[str, int], dict[str, Any]] = {}
        # Key: city_id → {"ts": float, "sun": {...}}
        self._sun_cache: dict[str, dict[str, Any]] = {}

        # Runtime state
        self._cycle_count = 0
        self._last_scan_at: Optional[str] = None
        self._errors_since_start: int = 0
        self._recent_errors: list[dict] = []
        self._started_at = _utc_now_iso()

        # Load any prior state from disk (cycle_count survives restarts)
        self._load_state()

        log.info(
            "[CALENDAR-AGENT] initialized — modules loaded: %s; data_dir=%s",
            self._modules_loaded,
            self.calendar_dir,
        )

    # ── Persistence ──────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            if self.state_path.exists():
                with self.state_path.open() as f:
                    data = json.load(f)
                self._cycle_count = int(data.get("cycle_count", 0))
                self._last_scan_at = data.get("last_scan_at")
                self._errors_since_start = 0  # always reset per-process
        except Exception as e:
            log.warning("[CALENDAR-AGENT] state load failed: %s", e)

    def _persist_state(self) -> None:
        try:
            payload = {
                "last_scan_at": self._last_scan_at,
                "cycle_count": self._cycle_count,
                "errors_since_start": self._errors_since_start,
                "recent_errors": self._recent_errors[-25:],
                "modules_loaded": self._modules_loaded,
                "started_at": self._started_at,
                "persisted_at": _utc_now_iso(),
            }
            tmp = self.state_path.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump(payload, f, indent=2)
            tmp.replace(self.state_path)
        except Exception as e:
            log.warning("[CALENDAR-AGENT] state persist failed: %s", e)

    def _record_error(self, where: str, exc: Exception) -> None:
        self._errors_since_start += 1
        self._recent_errors.append({
            "where": where,
            "error": f"{type(exc).__name__}: {exc}",
            "at": _utc_now_iso(),
        })
        # bound the in-memory buffer
        if len(self._recent_errors) > 100:
            self._recent_errors = self._recent_errors[-50:]

    # ── Scheduler entrypoint ─────────────────────────────────────────

    async def run(self) -> None:
        """
        Scheduler entrypoint — infinite 15-minute loop.

        Honors self._stop so the scheduler can shut us down cleanly.
        Catches and logs every exception so a transient failure can't
        kill the loop.
        """
        log.info("[CALENDAR-AGENT] loop spawned, scan_interval=%ds", SCAN_INTERVAL_S)
        # Defer first run by a few seconds so we don't compete with startup
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise

        while not self._stop:
            try:
                summary = await self.scan_cycle()
                log.info(
                    "[CALENDAR-AGENT] cycle %d done — cities=%d duration=%.1fs errors=%d",
                    self._cycle_count,
                    summary.get("cities_scanned", 0),
                    summary.get("duration_s", 0.0),
                    len(summary.get("errors", [])),
                )
            except asyncio.CancelledError:
                log.info("[CALENDAR-AGENT] cancelled, exiting loop")
                raise
            except Exception as e:  # noqa: BLE001
                log.error("[CALENDAR-AGENT] scan_cycle crashed: %s", e, exc_info=True)
                self._record_error("scan_cycle", e)

            # Sleep in small slices so stop flag is responsive
            slept = 0
            while slept < SCAN_INTERVAL_S and not self._stop:
                try:
                    await asyncio.sleep(min(30, SCAN_INTERVAL_S - slept))
                except asyncio.CancelledError:
                    log.info("[CALENDAR-AGENT] cancelled during sleep")
                    raise
                slept += 30

        log.info("[CALENDAR-AGENT] stop flag set, loop exiting")

    def stop(self) -> None:
        """Signal the run() loop to exit at the next slice."""
        self._stop = True

    # ── Active cities ────────────────────────────────────────────────

    async def _get_active_cities(self) -> list[str]:
        cities_pref = self._modules.get("cities_pref")
        if cities_pref is None:
            return list(DEFAULT_CITIES)

        try:
            getter = getattr(cities_pref, "get_all_active_cities", None)
            if getter is None:
                return list(DEFAULT_CITIES)
            result = await _maybe_await(getter)
            if isinstance(result, list) and result:
                # Normalize to ids if dicts were returned
                ids: list[str] = []
                for c in result:
                    if isinstance(c, str):
                        ids.append(c)
                    elif isinstance(c, dict):
                        cid = c.get("id") or c.get("city_id") or c.get("slug")
                        if cid:
                            ids.append(str(cid))
                return ids or list(DEFAULT_CITIES)
            return list(DEFAULT_CITIES)
        except Exception as e:
            log.warning("[CALENDAR-AGENT] cities_pref failed: %s", e)
            self._record_error("cities_pref.get_all_active_cities", e)
            return list(DEFAULT_CITIES)

    async def _get_default_city(self) -> str:
        cities_pref = self._modules.get("cities_pref")
        if cities_pref is not None:
            try:
                getter = getattr(cities_pref, "get_default_city", None)
                if getter is not None:
                    result = await _maybe_await(getter)
                    if isinstance(result, str) and result:
                        return result
                    if isinstance(result, dict):
                        cid = result.get("id") or result.get("city_id") or result.get("slug")
                        if cid:
                            return str(cid)
            except Exception as e:
                log.warning("[CALENDAR-AGENT] cities_pref.get_default_city failed: %s", e)
                self._record_error("cities_pref.get_default_city", e)
        return DEFAULT_CITIES[0]

    # ── Compile events (cache-first) ─────────────────────────────────

    async def compile_events(self, city_id: str, window_days: int) -> list[dict]:
        """
        Cache-first read used by iOS / FastAPI. If cached value is fresh
        (< EVENT_CACHE_MAX_AGE_S), return it; else compile and cache.
        """
        key = (city_id, int(window_days))
        cached = self._events_cache.get(key)
        if cached and (time.time() - cached["ts"]) < EVENT_CACHE_MAX_AGE_S:
            return cached["events"]
        return await self._refresh_events(city_id, window_days)

    async def _refresh_events(self, city_id: str, window_days: int) -> list[dict]:
        """Always do a fresh compile and update the cache."""
        events_compiler = self._modules.get("events_compiler")
        events: list[dict] = []

        if events_compiler is None:
            log.debug("[CALENDAR-AGENT] events_compiler missing — empty event list for %s/%d",
                      city_id, window_days)
            self._events_cache[(city_id, int(window_days))] = {
                "ts": time.time(),
                "events": events,
                "event_ids": frozenset(),
            }
            return events

        try:
            # Prefer get_cached_compile if the module exposes it, else compile fresh
            getter = getattr(events_compiler, "compile_unified_events", None)
            if getter is None:
                log.warning("[CALENDAR-AGENT] events_compiler has no compile_unified_events")
                return events
            result = await _call_with_compat(
                getter,
                # Newer signature (city_id, window_days)
                kwargs_options=[
                    {"city_id": city_id, "window_days": int(window_days)},
                    # Existing signature (city_id, start, end) — date window
                    {"city_id": city_id,
                     "start": date.today(),
                     "end": date.today() + timedelta(days=int(window_days))},
                ],
                positional_options=[
                    (city_id, int(window_days)),
                    (city_id, date.today(), date.today() + timedelta(days=int(window_days))),
                ],
            )
            if isinstance(result, list):
                events = result
            elif isinstance(result, dict) and "events" in result:
                events = list(result["events"])
            else:
                log.warning("[CALENDAR-AGENT] events_compiler returned unexpected type: %s",
                            type(result).__name__)
        except Exception as e:
            log.error("[CALENDAR-AGENT] events compile failed for %s/%d: %s",
                      city_id, window_days, e, exc_info=True)
            self._record_error(f"events_compiler({city_id},{window_days})", e)

        self._events_cache[(city_id, int(window_days))] = {
            "ts": time.time(),
            "events": events,
            "event_ids": _event_id_set(events),
        }
        return events

    # ── Sun state (cache-first) ──────────────────────────────────────

    async def get_sun_state(self, city_id: str) -> dict:
        """Cache-first solar/space-weather snapshot for a city."""
        cached = self._sun_cache.get(city_id)
        if cached and (time.time() - cached["ts"]) < SUN_CACHE_MAX_AGE_S:
            return cached["sun"]
        return await self._refresh_sun(city_id)

    async def _refresh_sun(self, city_id: str) -> dict:
        solar = self._modules.get("solar")
        if solar is None:
            sun: dict = {"city_id": city_id, "available": False, "reason": "solar_service missing"}
            self._sun_cache[city_id] = {"ts": time.time(), "sun": sun}
            return sun

        sun: dict = {}
        try:
            getter = getattr(solar, "get_full_solar_state", None)
            if getter is None:
                # fall back to legacy combined dashboard
                getter = getattr(solar, "get_sun_dashboard", None)
            if getter is None:
                sun = {"city_id": city_id, "available": False,
                       "reason": "no get_full_solar_state / get_sun_dashboard"}
            else:
                sun = await _maybe_await(getter, city_id)
                if not isinstance(sun, dict):
                    sun = {"city_id": city_id, "available": False,
                           "reason": f"unexpected return type {type(sun).__name__}"}
        except Exception as e:
            log.error("[CALENDAR-AGENT] sun fetch failed for %s: %s", city_id, e, exc_info=True)
            self._record_error(f"solar.get_full_solar_state({city_id})", e)
            sun = {"city_id": city_id, "available": False, "error": str(e)}

        self._sun_cache[city_id] = {"ts": time.time(), "sun": sun}
        return sun

    # ── Moon state (lunar.py — no caching needed; cheap) ─────────────

    def _get_moon(self) -> dict:
        lunar = self._modules.get("lunar")
        if lunar is None:
            return {"available": False, "reason": "lunar module missing"}
        try:
            phase_fn = getattr(lunar, "get_moon_phase", None)
            ctx_fn = getattr(lunar, "get_cycle_context", None)
            phase = phase_fn() if phase_fn else {}
            ctx = ctx_fn() if ctx_fn else {}
            return {"phase": phase, "cycle_context": ctx, "available": True}
        except Exception as e:
            log.warning("[CALENDAR-AGENT] lunar fetch failed: %s", e)
            self._record_error("lunar", e)
            return {"available": False, "error": str(e)}

    # ── Correlator ───────────────────────────────────────────────────

    async def _correlate(
        self,
        events: list[dict],
        moon: dict,
        sun: dict,
        city_id: str,
        window_days: int,
    ) -> list[dict]:
        correlator = self._modules.get("correlator")
        if correlator is None:
            return events
        attach = getattr(correlator, "attach_correlations", None)
        if attach is None:
            return events

        # The moon dict from _get_moon() wraps phase + context; pass the phase
        # directly when the correlator wants a phase, else the full bundle.
        moon_phase = moon.get("phase") if isinstance(moon, dict) and "phase" in moon else moon
        now_dt = datetime.now(timezone.utc)

        try:
            result = await _call_with_compat(
                attach,
                kwargs_options=[
                    # Spec'd signature
                    {"events": events, "moon": moon, "sun": sun,
                     "city_id": city_id, "window_days": int(window_days)},
                    # Existing signature: (events, solar_state, moon_phase, now)
                    {"events": events, "solar_state": sun,
                     "moon_phase": moon_phase, "now": now_dt},
                ],
                positional_options=[
                    (events, moon, sun, city_id, int(window_days)),
                    (events, sun, moon_phase, now_dt),
                    (events, sun, moon_phase),
                ],
            )
            if isinstance(result, list):
                return result
            return events
        except Exception as e:
            log.warning("[CALENDAR-AGENT] correlator failed for %s/%d: %s",
                        city_id, window_days, e)
            self._record_error(f"correlator({city_id},{window_days})", e)
            return events

    # ── TODO generation (cost-guarded) ───────────────────────────────

    async def get_todos(self, city_id: str, window_days: int) -> list[dict]:
        """
        Cache-first read API for iOS. Returns cached todos if fresh,
        else triggers regeneration.
        """
        key = (city_id, int(window_days))
        cached = self._todos_cache.get(key)
        # Read API has its own TTL — return cache if it exists and isn't stale
        if cached and (time.time() - cached["ts"]) < EVENT_CACHE_MAX_AGE_S:
            return cached["todos"]
        # Otherwise compile a fresh batch (this may still skip LLM if events unchanged)
        events = await self.compile_events(city_id, window_days)
        return await self._maybe_regen_todos(city_id, window_days, events)

    async def _maybe_regen_todos(
        self,
        city_id: str,
        window_days: int,
        events: list[dict],
    ) -> list[dict]:
        """
        Run the TODO generator — but skip if the most recent cache is
        < TODO_CACHE_MIN_AGE_S old AND the event id set hasn't changed.
        This is the cost guard.
        """
        key = (city_id, int(window_days))
        cached = self._todos_cache.get(key)
        new_event_ids = _event_id_set(events)

        if cached:
            age = time.time() - cached["ts"]
            same_events = cached.get("source_event_ids") == new_event_ids
            if age < TODO_CACHE_MIN_AGE_S and same_events:
                log.debug(
                    "[CALENDAR-AGENT] todos cached %s/%d — skip LLM (age=%.0fs, events unchanged)",
                    city_id, window_days, age,
                )
                return cached["todos"]

        todo_gen = self._modules.get("todo_generator")
        todos: list[dict] = []
        if todo_gen is None:
            log.debug("[CALENDAR-AGENT] todo_generator missing — empty todo list")
            self._todos_cache[key] = {
                "ts": time.time(),
                "todos": todos,
                "source_event_ids": new_event_ids,
            }
            return todos

        try:
            gen = getattr(todo_gen, "generate_todos_for_window", None)
            if gen is None:
                log.warning("[CALENDAR-AGENT] todo_generator has no generate_todos_for_window")
                return todos
            # Try with optional solar/moon context if the function accepts it
            moon_bundle = self._get_moon()
            moon_phase = moon_bundle.get("phase") if isinstance(moon_bundle, dict) else None
            sun_state = self._sun_cache.get(city_id, {}).get("sun")

            result = await _call_with_compat(
                gen,
                kwargs_options=[
                    {"city_id": city_id, "window_days": int(window_days),
                     "events": events, "solar_state": sun_state, "moon_phase": moon_phase},
                    {"city_id": city_id, "window_days": int(window_days), "events": events},
                ],
                positional_options=[
                    (city_id, int(window_days), events),
                ],
            )
            if isinstance(result, list):
                todos = result
            elif isinstance(result, dict) and "todos" in result:
                todos = list(result["todos"])
        except Exception as e:
            log.error("[CALENDAR-AGENT] todo generation failed for %s/%d: %s",
                      city_id, window_days, e, exc_info=True)
            self._record_error(f"todo_generator({city_id},{window_days})", e)

        self._todos_cache[key] = {
            "ts": time.time(),
            "todos": todos,
            "source_event_ids": new_event_ids,
        }
        return todos

    # ── Solar snapshot to disk (delegate to Agent 1) ─────────────────

    async def _snapshot_solar(self, city_id: str) -> bool:
        solar = self._modules.get("solar")
        if solar is None:
            return False
        snap = getattr(solar, "snapshot_to_disk", None)
        if snap is None:
            return False
        try:
            await _maybe_await(snap, city_id)
            return True
        except Exception as e:
            log.warning("[CALENDAR-AGENT] solar snapshot failed for %s: %s", city_id, e)
            self._record_error(f"solar.snapshot_to_disk({city_id})", e)
            return False

    # ── One full scan cycle ──────────────────────────────────────────

    async def scan_cycle(self) -> dict:
        """
        One full pass:
          1. Get active cities (default ["edmonton"] if cities_pref missing)
          2. For each (city, window) in [7, 30]:
             a. Compile events
             b. Pull solar + moon
             c. Attach correlations
             d. Generate (or skip) todos
             e. Persist via the dependency modules' own persistence
          3. Snapshot solar for the default city
          4. Return summary dict
        """
        t0 = time.time()
        errors: list[dict] = []

        cities = await self._get_active_cities()
        events_per_city: dict[str, dict[int, int]] = {}
        todos_per_city: dict[str, dict[int, int]] = {}

        # Per-cycle moon is global — fetch once
        moon = self._get_moon()

        for city_id in cities:
            events_per_city[city_id] = {}
            todos_per_city[city_id] = {}

            # Sun state per city (cached per call)
            try:
                sun = await self._refresh_sun(city_id)
            except Exception as e:  # noqa: BLE001
                errors.append({"city": city_id, "step": "sun", "error": str(e)})
                self._record_error(f"scan.sun({city_id})", e)
                sun = {"available": False, "error": str(e)}

            for window in DEFAULT_WINDOWS:
                # a. events
                pre_evt_err_count = self._errors_since_start
                try:
                    events = await self._refresh_events(city_id, window)
                except Exception as e:  # noqa: BLE001
                    errors.append({"city": city_id, "window": window, "step": "events",
                                   "error": str(e)})
                    self._record_error(f"scan.events({city_id},{window})", e)
                    events = []
                if self._errors_since_start > pre_evt_err_count:
                    last = self._recent_errors[-1] if self._recent_errors else {}
                    errors.append({"city": city_id, "window": window, "step": "events",
                                   "error": last.get("error", "internal events error")})

                # b. correlate
                pre_corr_err_count = self._errors_since_start
                try:
                    events = await self._correlate(events, moon, sun, city_id, window)
                except Exception as e:  # noqa: BLE001
                    errors.append({"city": city_id, "window": window, "step": "correlate",
                                   "error": str(e)})
                    self._record_error(f"scan.correlate({city_id},{window})", e)
                if self._errors_since_start > pre_corr_err_count:
                    # Internal correlator error already recorded; surface it in summary
                    last = self._recent_errors[-1] if self._recent_errors else {}
                    errors.append({"city": city_id, "window": window, "step": "correlate",
                                   "error": last.get("error", "internal correlator error")})

                # Update cache with possibly-correlated events (preserves id-set)
                self._events_cache[(city_id, int(window))] = {
                    "ts": time.time(),
                    "events": events,
                    "event_ids": _event_id_set(events),
                }
                events_per_city[city_id][window] = len(events)

                # c. todos (cost-guarded)
                pre_todo_err_count = self._errors_since_start
                try:
                    todos = await self._maybe_regen_todos(city_id, window, events)
                except Exception as e:  # noqa: BLE001
                    errors.append({"city": city_id, "window": window, "step": "todos",
                                   "error": str(e)})
                    self._record_error(f"scan.todos({city_id},{window})", e)
                    todos = []
                if self._errors_since_start > pre_todo_err_count:
                    last = self._recent_errors[-1] if self._recent_errors else {}
                    errors.append({"city": city_id, "window": window, "step": "todos",
                                   "error": last.get("error", "internal todos error")})
                todos_per_city[city_id][window] = len(todos)

        # Snapshot solar for default city only (cost: 1 write/cycle)
        try:
            default_city = await self._get_default_city()
            await self._snapshot_solar(default_city)
        except Exception as e:  # noqa: BLE001
            errors.append({"step": "solar_snapshot", "error": str(e)})
            self._record_error("scan.snapshot", e)

        duration = time.time() - t0
        self._cycle_count += 1
        self._last_scan_at = _utc_now_iso()
        self._persist_state()

        return {
            "cities_scanned": len(cities),
            "cities": cities,
            "events_per_city": events_per_city,
            "todos_per_city": todos_per_city,
            "duration_s": round(duration, 2),
            "errors": errors,
            "cycle_count": self._cycle_count,
            "last_scan_at": self._last_scan_at,
            "modules_loaded": self._modules_loaded,
        }

    # ── Status (read-only) ───────────────────────────────────────────

    async def get_status(self) -> dict:
        cities = await self._get_active_cities()
        return {
            "last_scan_at": self._last_scan_at,
            "cycle_count": self._cycle_count,
            "errors_since_start": self._errors_since_start,
            "recent_errors": list(self._recent_errors[-10:]),
            "cities_active": cities,
            "modules_loaded": self._modules_loaded,
            "scan_interval_s": SCAN_INTERVAL_S,
            "todo_cache_min_age_s": TODO_CACHE_MIN_AGE_S,
            "events_cached": len(self._events_cache),
            "todos_cached": len(self._todos_cache),
            "sun_cached": len(self._sun_cache),
            "started_at": self._started_at,
            "stopped": self._stop,
        }


# ── Singleton accessor ───────────────────────────────────────────────

_calendar_agent_instance: Optional[CalendarAgent] = None


def get_calendar_agent(brain: Any = None) -> CalendarAgent:
    """
    Module-level singleton accessor. Routes and the scheduler should
    use this — never instantiate CalendarAgent directly in production.

    If a brain is passed on the first call it's wired in; subsequent
    calls return the same instance regardless of the brain arg.
    """
    global _calendar_agent_instance
    if _calendar_agent_instance is None:
        _calendar_agent_instance = CalendarAgent(brain=brain)
    return _calendar_agent_instance


def reset_calendar_agent_for_tests() -> None:
    """Test helper — wipe the singleton between test cases."""
    global _calendar_agent_instance
    if _calendar_agent_instance is not None:
        _calendar_agent_instance.stop()
    _calendar_agent_instance = None


__all__ = [
    "CalendarAgent",
    "get_calendar_agent",
    "reset_calendar_agent_for_tests",
    "SCAN_INTERVAL_S",
    "TODO_CACHE_MIN_AGE_S",
]
