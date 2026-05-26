"""ncl-morning-quiz scheduler (Wave 14E followup, 2026-05-25).

Two-stage scheduler:

1. **Midnight carry-forward** — at 00:05 ET, look at yesterday's quiz; if
   present, write a pre-filled template for today carrying forward the
   market_posture + research_question. NATRIX wakes up to a partially-filled
   quiz so he edits rather than starts blank.

2. **6:00 ET nudge** — if today's quiz is still on the template (or no quiz
   on disk), ntfy push: "Morning quiz — take 90 seconds". Quiet on
   weekends unless NCL_QUIZ_NUDGE_WEEKENDS=1. Second-chance nudge at noon
   if still not submitted.

The loop is idempotent: tracks "last nudge sent" per date in
data/journal/morning-quiz/scheduler-state.json so re-bouncing doesn't
double-fire.

Pulled into the autonomous scheduler via `_morning_quiz_loop()` in
runtime/autonomous/scheduler.py (registered in Wave 14E followup).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

# Eastern Time for operator-local scheduling (NATRIX is ET).
_ET = ZoneInfo("America/New_York")

# Cadence
_TICK_INTERVAL_S = 60  # check once per minute
_MIDNIGHT_AT = time(0, 5)          # 00:05 ET
_NUDGE_AT = time(6, 0)             # 06:00 ET
_NUDGE_2_AT = time(12, 0)          # 12:00 ET — second-chance

# Filesystem
_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
_QUIZ_DIR = _BASE / "data" / "journal" / "morning-quiz"
_STATE_FILE = _QUIZ_DIR / "scheduler-state.json"


def _now_et() -> datetime:
    return datetime.now(_ET)


def _today_str() -> str:
    return _now_et().strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (_now_et() - timedelta(days=1)).strftime("%Y-%m-%d")


def _quiz_file(date_str: str) -> Path:
    return _QUIZ_DIR / f"{date_str}.json"


def _load_state() -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _QUIZ_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _quiz_complete_for(date_str: str) -> bool:
    """A quiz is 'complete' if the file exists and was user-submitted (not template)."""
    f = _quiz_file(date_str)
    if not f.exists():
        return False
    try:
        data = json.loads(f.read_text())
        return not bool(data.get("is_template", False))
    except Exception:
        return False


def _write_template(date_str: str, yesterday: dict | None) -> None:
    """Write tomorrow's template carrying forward yesterday's posture + research."""
    if _quiz_file(date_str).exists():
        return  # don't overwrite an existing real submission
    template = {
        "quiz_id": f"mq-template-{date_str}",
        "date": date_str,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "mood_score": (yesterday or {}).get("mood_score", 7),
        "mood_word": "",
        "top_priority": "",
        "supporting_tasks": [],
        "market_posture": (yesterday or {}).get("market_posture", "neutral"),
        "research_question": (yesterday or {}).get("research_question", ""),
        "gratitude": "",
        "yesterday_lesson": "",
        "notes": "",
        "is_template": True,                             # quiz_complete_for returns False
        "carried_forward_from": (yesterday or {}).get("date", ""),
        "journal_entry_id": "",
        "lesson_entry_id": "",
        "pushed_to_working_context": False,
        "pushed_to_calendar_todos": False,
        "pushed_to_morning_brief": False,
        "wisdom_id_shown": "",
    }
    _QUIZ_DIR.mkdir(parents=True, exist_ok=True)
    _quiz_file(date_str).write_text(json.dumps(template, indent=2))


def _load_yesterday() -> dict | None:
    f = _quiz_file(_yesterday_str())
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


async def _send_ntfy(title: str, body: str) -> None:
    """Best-effort ntfy push. NCL_NTFY_TOPIC env should be set.

    Uses ntfy's JSON POST API so UTF-8 in the title (em-dash, emoji,
    accented letters) doesn't crash the HTTP header encoder. HTTP
    headers must be ASCII; the JSON body is UTF-8 safe.

    Fixes the 2026-05-26 06:00 ET crash:
        [QUIZ-SCHED] ntfy failed: 'ascii' codec can't encode
        character '\\u2014' in position 13
    """
    try:
        import httpx

        topic = os.getenv("NCL_NTFY_TOPIC", "ncl-natrix-intel-7x9k")
        if not topic:
            return
        payload = {
            "topic": topic,
            "title": title,
            "message": body,
            "priority": 4,  # high (1=min, 5=max)
            "tags": ["sun_with_face", "books"],
            "click": "firststrike://journal/morning-quiz",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post("https://ntfy.sh/", json=payload)
            r.raise_for_status()
        log.info("[QUIZ-SCHED] ntfy sent: %s", title)
    except Exception as e:
        log.warning("[QUIZ-SCHED] ntfy failed: %s", e)


def _within_minute(now_et: datetime, target: time) -> bool:
    """True if now is within the minute after target (00:05 - 00:05:59)."""
    return now_et.hour == target.hour and now_et.minute == target.minute


async def run(scheduler) -> None:
    """Long-running morning-quiz scheduler loop.

    Lifecycle managed by the autonomous scheduler. Restarts via the
    supervisor if it crashes (up to 3 restarts per scheduler lifetime).
    """
    log.info("[QUIZ-SCHED] morning quiz scheduler started")
    while getattr(scheduler, "_running", True):
        try:
            now = _now_et()
            today = now.strftime("%Y-%m-%d")
            state = _load_state()

            # 1) Midnight carry-forward
            if _within_minute(now, _MIDNIGHT_AT):
                key = f"template-{today}"
                if not state.get(key):
                    yesterday = _load_yesterday()
                    _write_template(today, yesterday)
                    state[key] = now.isoformat()
                    _save_state(state)
                    log.info("[QUIZ-SCHED] wrote template for %s (yesterday=%s)",
                             today, (yesterday or {}).get("date", "<none>"))

            # 2) 06:00 ET nudge
            if _within_minute(now, _NUDGE_AT):
                key = f"nudge1-{today}"
                if not state.get(key) and not _quiz_complete_for(today):
                    weekend = now.weekday() >= 5
                    nudge_weekends = os.getenv("NCL_QUIZ_NUDGE_WEEKENDS", "0") == "1"
                    if not weekend or nudge_weekends:
                        await _send_ntfy(
                            title="Morning Quiz — 90s",
                            body="Open FirstStrike → Journal → Quiz to set today's intention.",
                        )
                        state[key] = now.isoformat()
                        _save_state(state)

            # 3) Noon second-chance nudge
            if _within_minute(now, _NUDGE_2_AT):
                key = f"nudge2-{today}"
                if not state.get(key) and not _quiz_complete_for(today):
                    weekend = now.weekday() >= 5
                    nudge_weekends = os.getenv("NCL_QUIZ_NUDGE_WEEKENDS", "0") == "1"
                    if not weekend or nudge_weekends:
                        await _send_ntfy(
                            title="Morning Quiz — second call",
                            body="Quiz still empty; quick set-an-intention?",
                        )
                        state[key] = now.isoformat()
                        _save_state(state)

        except Exception as e:
            log.exception("[QUIZ-SCHED] cycle error: %s", e)

        await asyncio.sleep(_TICK_INTERVAL_S)

    log.info("[QUIZ-SCHED] morning quiz scheduler stopped")
