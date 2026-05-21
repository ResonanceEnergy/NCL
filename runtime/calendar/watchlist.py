"""
Watchlist / suggested to-do engine — correlates moon energy with full intel pipeline.

Pulls from:
  - Moon phase energy state (lunar.py)
  - Predictions (future_predictor)
  - Scanner alerts (GOAT/Bravo)
  - Council recommendations
  - Journal prompts / reflection
  - Trading goals / paper trades
  - Portfolio rebalancing signals
  - Calendar events (market + local)

Produces a prioritized daily action list framed by lunar energy.
"""
from __future__ import annotations

import logging
import os
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("ncl.calendar.watchlist")


# ── Watchlist item categories ────────────────────────────────────────

WATCHLIST_CATEGORIES = {
    "moon": {"label": "Lunar", "color": "#9C88FF", "icon": "moon.stars.fill", "priority": 1},
    "prediction": {"label": "Prediction", "color": "#00BFFF", "icon": "eye", "priority": 5},
    "scanner": {"label": "Scanner", "color": "#2ECC71", "icon": "antenna.radiowaves.left.and.right", "priority": 4},
    "council": {"label": "Council", "color": "#E67E22", "icon": "person.3.fill", "priority": 4},
    "journal": {"label": "Journal", "color": "#1ABC9C", "icon": "book.fill", "priority": 2},
    "trading": {"label": "Trading", "color": "#F39C12", "icon": "chart.line.uptrend.xyaxis", "priority": 5},
    "portfolio": {"label": "Portfolio", "color": "#3498DB", "icon": "briefcase.fill", "priority": 3},
    "calendar": {"label": "Calendar", "color": "#E94560", "icon": "calendar", "priority": 4},
    "intel": {"label": "Intel", "color": "#9B59B6", "icon": "brain", "priority": 3},
    "system": {"label": "System", "color": "#95A5A6", "icon": "gearshape", "priority": 1},
}


# ── Core watchlist builder ───────────────────────────────────────────

async def build_watchlist(
    brain_client=None,
    moon_phase: dict | None = None,
    cycle_context: dict | None = None,
) -> list[dict]:
    """
    Build the full correlated watchlist/to-do for today.

    Each item:
      {
        "id": int,
        "priority": 1-5,
        "action": str,
        "category": str,
        "category_label": str,
        "category_color": str,
        "category_icon": str,
        "source": str,           # which system generated this
        "context": str,          # why this matters now
        "urgency": "now"|"today"|"this_week",
        "energy_aligned": bool,  # does this align with current moon energy?
      }
    """
    todos = []
    energy_mode = ""
    if moon_phase:
        energy_mode = moon_phase.get("energy_mode", "").lower()

    # 1. Moon energy actions (always present)
    if moon_phase:
        todos.extend(_moon_energy_todos(moon_phase, cycle_context))

    # 2. Pull from Brain endpoints if client available
    if brain_client:
        todos.extend(await _prediction_todos(brain_client, energy_mode))
        todos.extend(await _scanner_todos(brain_client, energy_mode))
        todos.extend(await _council_todos(brain_client, energy_mode))
        todos.extend(await _journal_todos(brain_client, energy_mode))
        todos.extend(await _paper_trade_todos(brain_client, energy_mode))
        todos.extend(await _portfolio_todos(brain_client, energy_mode))
        todos.extend(await _calendar_event_todos(brain_client, energy_mode))

    # Assign IDs, sort by priority (highest first), then urgency
    urgency_order = {"now": 0, "today": 1, "this_week": 2}
    todos.sort(key=lambda t: (-t.get("priority", 0), urgency_order.get(t.get("urgency", "today"), 1)))

    for i, todo in enumerate(todos):
        todo["id"] = i
        cat = todo.get("category", "system")
        meta = WATCHLIST_CATEGORIES.get(cat, WATCHLIST_CATEGORIES["system"])
        todo["category_label"] = meta["label"]
        todo["category_color"] = meta["color"]
        todo["category_icon"] = meta["icon"]

    return todos


# ── Moon energy todos ────────────────────────────────────────────────

def _moon_energy_todos(phase: dict, context: dict | None) -> list[dict]:
    """Generate todos from moon phase energy state."""
    todos = []
    mode = phase.get("energy_mode", "").lower()
    actions = phase.get("suggested_actions", [])

    for action in actions:
        todos.append({
            "priority": 2,
            "action": action,
            "category": "moon",
            "source": "lunar_engine",
            "context": f"{phase.get('phase_name', '')} -- {mode} phase energy",
            "urgency": "today",
            "energy_aligned": True,
        })

    # Add phase-transition awareness
    if context:
        days_to_full = context.get("days_to_full_moon", 99)
        days_to_new = context.get("days_to_new_moon", 99)

        if days_to_full and days_to_full <= 2:
            todos.append({
                "priority": 4,
                "action": "Full moon approaching -- prepare to harvest positions and assess all open trades",
                "category": "moon",
                "source": "lunar_engine",
                "context": f"Full moon in {int(days_to_full)} day(s). Peak energy for assessment.",
                "urgency": "now",
                "energy_aligned": True,
            })
        elif days_to_new and days_to_new <= 2:
            todos.append({
                "priority": 4,
                "action": "New moon approaching -- set intentions, plan new entries, review strategy",
                "category": "moon",
                "source": "lunar_engine",
                "context": f"New moon in {int(days_to_new)} day(s). Reset energy for fresh cycle.",
                "urgency": "now",
                "energy_aligned": True,
            })

    return todos


# ── Prediction-based todos ───────────────────────────────────────────

async def _prediction_todos(client, energy_mode: str) -> list[dict]:
    """Pull high-confidence predictions that need attention."""
    todos = []
    try:
        result = _sync_brain_call(client, "/predictions", "GET")
        predictions = result.get("predictions", [])

        high_conf = [p for p in predictions if (p.get("confidence", 0) or 0) >= 70]
        for pred in high_conf[:3]:
            topic = pred.get("topic", pred.get("title", "Unknown"))
            conf = pred.get("confidence", 0)
            direction = pred.get("direction", "")

            aligned = energy_mode in ("push", "build", "initiate") and direction == "bullish"
            aligned = aligned or (energy_mode in ("release", "reflect") and direction == "bearish")

            todos.append({
                "priority": 5,
                "action": f"High-confidence prediction ({conf}%): {topic}",
                "category": "prediction",
                "source": "predictions",
                "context": f"Direction: {direction}. {'Aligned with ' + energy_mode + ' energy.' if aligned else 'Counter-trend to current energy.'}",
                "urgency": "today",
                "energy_aligned": aligned,
            })

        # Check for convergence signals
        conv_result = _sync_brain_call(client, "/prediction/convergence", "GET")
        convergences = conv_result.get("convergences", [])
        if convergences:
            topics = [c.get("topic", "") for c in convergences[:2]]
            todos.append({
                "priority": 5,
                "action": f"Convergence detected across {len(convergences)} predictions -- review alignment",
                "category": "prediction",
                "source": "convergence",
                "context": f"Topics: {', '.join(topics)}",
                "urgency": "now",
                "energy_aligned": True,
            })

    except Exception as e:
        log.debug("Prediction todos skipped: %s", e)

    return todos


# ── Scanner-based todos ──────────────────────────────────────────────

async def _scanner_todos(client, energy_mode: str) -> list[dict]:
    """Pull scanner hits that need review."""
    todos = []
    try:
        # GOAT scanner
        goat = _sync_brain_call(client, "/scanner/goat", "GET")
        goat_hits = goat.get("results", goat.get("hits", []))
        if goat_hits:
            symbols = [h.get("symbol", "") for h in goat_hits[:5]]
            aligned = energy_mode in ("initiate", "build", "push")
            todos.append({
                "priority": 4,
                "action": f"GOAT scanner: {len(goat_hits)} hits -- {', '.join(symbols)}",
                "category": "scanner",
                "source": "goat_scanner",
                "context": f"{'Waxing energy favors new entries' if aligned else 'Waning energy -- be selective'}",
                "urgency": "today",
                "energy_aligned": aligned,
            })

        # Bravo scanner
        bravo = _sync_brain_call(client, "/scanner/bravo", "GET")
        bravo_hits = bravo.get("results", bravo.get("hits", []))
        if bravo_hits:
            symbols = [h.get("symbol", "") for h in bravo_hits[:5]]
            todos.append({
                "priority": 4,
                "action": f"Bravo swing: {len(bravo_hits)} setups -- {', '.join(symbols)}",
                "category": "scanner",
                "source": "bravo_scanner",
                "context": "Swing setups identified. Review entry criteria.",
                "urgency": "today",
                "energy_aligned": energy_mode in ("initiate", "build", "push"),
            })

    except Exception as e:
        log.debug("Scanner todos skipped: %s", e)

    return todos


# ── Council-based todos ──────────────────────────────────────────────

async def _council_todos(client, energy_mode: str) -> list[dict]:
    """Pull recent council recommendations needing action."""
    todos = []
    try:
        result = _sync_brain_call(client, "/councils/reports?limit=3", "GET")
        reports = result.get("reports", [])

        for report in reports[:2]:
            title = report.get("title", report.get("topic", "Council report"))
            summary = report.get("summary", "")
            if summary:
                summary = summary[:80] + "..." if len(summary) > 80 else summary

            todos.append({
                "priority": 3,
                "action": f"Review council: {title}",
                "category": "council",
                "source": "council_reports",
                "context": summary or "Recent council session needs your review",
                "urgency": "this_week",
                "energy_aligned": energy_mode in ("analyze", "harvest", "refine"),
            })

    except Exception as e:
        log.debug("Council todos skipped: %s", e)

    return todos


# ── Journal todos ────────────────────────────────────────────────────

async def _journal_todos(client, energy_mode: str) -> list[dict]:
    """Journal prompts based on moon phase and trading activity."""
    todos = []

    # Phase-specific journal prompts
    prompts = {
        "initiate": "Set intentions for this lunar cycle. What new positions or strategies are you considering?",
        "build": "Document momentum. What's building in your portfolio and mind?",
        "push": "Record your push decisions. Where are you pressing advantage?",
        "refine": "Fine-tune your approach. What adjustments are needed before peak?",
        "harvest": "Capture wins and learnings. What has come to fruition?",
        "analyze": "Deep analysis session. Review performance metrics and patterns.",
        "release": "What needs to go? Document positions, habits, or beliefs to release.",
        "reflect": "Quiet reflection. What did this cycle teach you?",
    }

    prompt = prompts.get(energy_mode, "Write today's journal entry.")
    todos.append({
        "priority": 2,
        "action": f"Journal: {prompt}",
        "category": "journal",
        "source": "journal_prompts",
        "context": f"{energy_mode.capitalize()} phase -- {prompt[:60]}",
        "urgency": "today",
        "energy_aligned": True,
    })

    # Check if journal entry exists today
    try:
        result = _sync_brain_call(client, "/journal/today", "GET")
        if not result.get("entry") and not result.get("entries"):
            todos[-1]["priority"] = 3  # Bump priority if no entry yet
            todos[-1]["urgency"] = "now"
    except Exception:
        pass

    return todos


# ── Paper trade todos ────────────────────────────────────────────────

async def _paper_trade_todos(client, energy_mode: str) -> list[dict]:
    """Review open paper trades, check graduation progress."""
    todos = []
    try:
        # Open trades
        result = _sync_brain_call(client, "/paper/trades?status=open", "GET")
        trades = result.get("trades", [])

        if trades:
            symbols = [t.get("symbol", "") for t in trades[:5]]
            todos.append({
                "priority": 4,
                "action": f"Review {len(trades)} open paper trades: {', '.join(symbols)}",
                "category": "trading",
                "source": "paper_trading",
                "context": "Check stop levels, update targets, record journal notes.",
                "urgency": "today",
                "energy_aligned": energy_mode in ("analyze", "refine", "harvest"),
            })

        # Graduation stats
        stats = _sync_brain_call(client, "/paper/stats", "GET")
        grad = stats.get("graduation", {})
        if grad:
            ready = grad.get("ready", False)
            progress = grad.get("progress_pct", 0)
            if ready:
                todos.append({
                    "priority": 5,
                    "action": "Paper trading graduation READY -- consider moving to live trades",
                    "category": "trading",
                    "source": "paper_graduation",
                    "context": "All graduation criteria met. Review stats before going live.",
                    "urgency": "now",
                    "energy_aligned": energy_mode in ("initiate", "push", "harvest"),
                })
            elif progress > 50:
                todos.append({
                    "priority": 2,
                    "action": f"Paper trading graduation: {progress:.0f}% complete",
                    "category": "trading",
                    "source": "paper_graduation",
                    "context": "Keep building your track record.",
                    "urgency": "this_week",
                    "energy_aligned": True,
                })

    except Exception as e:
        log.debug("Paper trade todos skipped: %s", e)

    return todos


# ── Portfolio todos ──────────────────────────────────────────────────

async def _portfolio_todos(client, energy_mode: str) -> list[dict]:
    """Portfolio rebalancing and review signals."""
    todos = []
    try:
        result = _sync_brain_call(client, "/portfolio/summary", "GET")
        summary = result

        # Check for concentration risk
        allocations = summary.get("allocations", [])
        for alloc in allocations:
            weight = alloc.get("weight", 0)
            name = alloc.get("name", alloc.get("symbol", ""))
            if weight > 15:
                todos.append({
                    "priority": 3,
                    "action": f"Concentration alert: {name} at {weight:.1f}% of portfolio",
                    "category": "portfolio",
                    "source": "portfolio_manager",
                    "context": "Consider rebalancing. Single position exceeds 15% threshold.",
                    "urgency": "this_week",
                    "energy_aligned": energy_mode in ("analyze", "release", "refine"),
                })

        # Daily P&L check
        daily_pnl = summary.get("daily_pnl", 0)
        if abs(daily_pnl) > 500:
            direction = "up" if daily_pnl > 0 else "down"
            todos.append({
                "priority": 4,
                "action": f"Notable P&L move: ${daily_pnl:+,.0f} today",
                "category": "portfolio",
                "source": "portfolio_manager",
                "context": f"Portfolio {direction} significantly. Review positions.",
                "urgency": "now",
                "energy_aligned": True,
            })

    except Exception as e:
        log.debug("Portfolio todos skipped: %s", e)

    return todos


# ── Calendar event todos ─────────────────────────────────────────────

async def _calendar_event_todos(client, energy_mode: str) -> list[dict]:
    """High-impact calendar events that need preparation."""
    todos = []
    try:
        today = date.today()
        end = today + timedelta(days=3)
        result = _sync_brain_call(
            client,
            f"/calendar/events?start={today.isoformat()}&end={end.isoformat()}",
            "GET",
        )
        events = result.get("events", [])

        high_impact = [e for e in events if e.get("impact") in ("high", "critical")]
        for event in high_impact[:3]:
            todos.append({
                "priority": 5 if event.get("impact") == "critical" else 4,
                "action": f"Upcoming: {event.get('title', 'Event')} ({event.get('date', '')})",
                "category": "calendar",
                "source": "calendar_events",
                "context": event.get("description", "High-impact event approaching. Prepare accordingly."),
                "urgency": "now" if event.get("date") == today.isoformat() else "today",
                "energy_aligned": True,
            })

    except Exception as e:
        log.debug("Calendar event todos skipped: %s", e)

    return todos


# ── Helper ───────────────────────────────────────────────────────────

def _sync_brain_call(client, endpoint: str, method: str) -> dict:
    """Synchronous wrapper for NCL Brain API calls within the Brain process itself."""
    # When running inside the Brain, we can call route handlers directly
    # or use the internal HTTP client
    try:
        import httpx as _httpx
        from runtime.api.routes import STRIKE_TOKEN

        url = f"http://127.0.0.1:8800{endpoint}"
        headers = {"Authorization": f"Bearer {STRIKE_TOKEN}"}

        with _httpx.Client(timeout=_httpx.Timeout(10.0)) as c:
            if method == "GET":
                resp = c.get(url, headers=headers)
            else:
                resp = c.post(url, headers=headers)

            if resp.status_code == 200:
                return resp.json()
            else:
                log.debug("Brain call %s returned %d", endpoint, resp.status_code)
                return {}
    except Exception as e:
        log.debug("Brain call %s failed: %s", endpoint, e)
        return {}
