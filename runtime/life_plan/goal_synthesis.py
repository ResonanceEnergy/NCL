"""LLM-driven goal synthesis — Wave 14F (2026-05-25).

Takes a quarterly OKR (`Goal` with scope="quarter") and asks Sonnet 4 to
produce 4-6 SMART weekly tasks per Key Result. Output Goals carry
scope="week", parent_goal_id pointing to the source, and a single
auto-generated key_result per task (so weekly progress can still be
tracked as 0/1 ratios). Budget-gated. Idempotent — re-synthesizing
replaces all prior weekly children of the same parent.

See docs/JOURNAL_REDESIGN_2026-05-25.md for the broader life-plan design.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

from .models import Goal, KeyResult
from .store import LifePlanStore


log = logging.getLogger("ncl.life_plan.synth")

_MODEL = os.getenv("NCL_GOAL_SYNTH_MODEL", "claude-sonnet-4-20250514")
_BUDGET = float(os.getenv("NCL_GOAL_SYNTH_BUDGET", "0.05"))
_TIMEOUT = float(os.getenv("NCL_GOAL_SYNTH_TIMEOUT", "60.0"))


def _next_week_dates() -> tuple[date, date]:
    """Monday-to-Sunday for the upcoming week."""
    today = date.today()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    start = today + timedelta(days=days_to_monday)
    end = start + timedelta(days=6)
    return start, end


async def _call_anthropic(prompt: str) -> Optional[str]:
    """Single Anthropic call, returns text or None on failure."""
    import httpx

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    # Budget gate (non-fatal — caller decides)
    try:
        from ..cost_tracker import check_budget

        if not await check_budget("anthropic", _BUDGET):
            log.warning("[GOAL-SYNTH] budget too low (need %.3f)", _BUDGET)
            return None
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            resp = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": _MODEL,
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("content", [{}])[0] or {}).get("text", "")

            # Track cost
            try:
                from ..cost_tracker import record_cost

                usage = data.get("usage", {}) or {}
                cost = (
                    int(usage.get("input_tokens", 0)) * 3.0
                    + int(usage.get("output_tokens", 0)) * 15.0
                ) / 1_000_000
                await record_cost(
                    "anthropic",
                    cost,
                    "goal_synth",
                    f"weekly synth in={usage.get('input_tokens',0)} out={usage.get('output_tokens',0)}",
                    model="claude-sonnet-4-20250514",
                    input_tokens=int(usage.get("input_tokens", 0)),
                    output_tokens=int(usage.get("output_tokens", 0)),
                )
            except Exception:
                pass

            return text
    except Exception as e:
        log.warning("[GOAL-SYNTH] anthropic call failed: %s", e)
        return None


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("empty response")
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    m = _JSON_BLOCK.search(cleaned)
    if not m:
        raise ValueError(f"no JSON in response: {cleaned[:200]!r}")
    return json.loads(m.group(0))


async def synthesize_weekly_tasks(
    parent_goal: Goal,
    *,
    store: LifePlanStore,
    replace_existing: bool = True,
) -> dict:
    """Generate 4-6 weekly SMART task Goals under a quarterly OKR.

    Returns dict:
      {
        "status": "ok" | "no_kr" | "no_response" | "parse_error" | "budget",
        "parent_goal_id": str,
        "weekly_goals_created": [goal_id, ...],
        "weekly_count": int,
        "raw_response": str | None,
      }
    """
    if not parent_goal.key_results:
        return {
            "status": "no_kr",
            "parent_goal_id": parent_goal.goal_id,
            "weekly_goals_created": [],
            "weekly_count": 0,
            "raw_response": None,
        }

    krs_lines = []
    for kr in parent_goal.key_results:
        krs_lines.append(
            f"- {kr.description} (target: {kr.target}{kr.unit}, current: {kr.current}{kr.unit}, "
            f"progress: {kr.progress_pct:.0f}%)"
        )
    krs_block = "\n".join(krs_lines)

    week_start, week_end = _next_week_dates()
    prompt = f"""You are NATRIX's life-planning assistant. Translate one QUARTERLY OKR into a focused weekly task plan that moves the needle THIS WEEK ({week_start.isoformat()} to {week_end.isoformat()}).

QUARTERLY OBJECTIVE:
{parent_goal.objective}

KEY RESULTS (current state):
{krs_block}

SCOPE: {parent_goal.scope}
QUARTER: {parent_goal.starts_at} to {parent_goal.ends_at}
CURRENT WEEK CONFIDENCE: {parent_goal.confidence}/10

Output ONLY valid JSON in this shape (no preamble, no markdown):

{{
  "themes": ["1-3 short themes the week is organized around"],
  "weekly_tasks": [
    {{
      "objective": "SMART, specific task — what NATRIX does THIS week",
      "rationale": "1 sentence: which KR this moves + why this week",
      "target_metric": "What success looks like by Sunday (numeric or boolean)",
      "target_value": 1.0,
      "unit": "count|hours|$|%|sessions|reps",
      "linked_kr_description": "Quote of the KR description this task targets"
    }}
  ]
}}

Rules:
- Produce 4-6 weekly tasks. NOT one per KR; the right number for actual weekly capacity.
- Each task must be SPECIFIC, MEASURABLE, ACHIEVABLE in 5-7 days, RELEVANT to a KR, TIME-BOUND to this week.
- Lead each objective with a verb (Ship, Call, Write, Run, Lift, Read, Buy).
- target_value + unit must be numeric so progress is trackable (1 done call, 3 hours of practice, $500 invested).
- Prefer leading indicators (actions NATRIX controls) over lagging ones (outcomes that depend on luck).

JSON only. Begin.""".strip()

    response = await _call_anthropic(prompt)
    if response is None:
        return {
            "status": "no_response",
            "parent_goal_id": parent_goal.goal_id,
            "weekly_goals_created": [],
            "weekly_count": 0,
            "raw_response": None,
        }

    try:
        plan = _extract_json(response)
    except Exception as e:
        log.warning("[GOAL-SYNTH] parse failed: %s", e)
        return {
            "status": "parse_error",
            "parent_goal_id": parent_goal.goal_id,
            "weekly_goals_created": [],
            "weekly_count": 0,
            "raw_response": response[:1000],
        }

    weekly_tasks = plan.get("weekly_tasks", []) or []
    if not weekly_tasks:
        return {
            "status": "no_tasks",
            "parent_goal_id": parent_goal.goal_id,
            "weekly_goals_created": [],
            "weekly_count": 0,
            "raw_response": response[:500],
        }

    # Replace existing weekly children of this parent if requested
    if replace_existing:
        existing = store.list_goals(scope="week", parent_goal_id=parent_goal.goal_id)
        for g in existing:
            g.status = "superseded"
            store.save_goal(g)

    created_ids: list[str] = []
    for task in weekly_tasks[:8]:  # cap at 8 even if model emits more
        try:
            target = float(task.get("target_value", 1.0) or 1.0)
        except (TypeError, ValueError):
            target = 1.0
        kr = KeyResult(
            description=task.get("target_metric", "Completed"),
            target=target,
            current=0.0,
            unit=str(task.get("unit", "count")),
        )
        weekly = Goal(
            scope="week",
            objective=task.get("objective", "(no objective)"),
            key_results=[kr],
            parent_goal_id=parent_goal.goal_id,
            starts_at=week_start,
            ends_at=week_end,
            status="active",
            confidence=7,
        )
        store.save_goal(weekly)
        created_ids.append(weekly.goal_id)

    log.info(
        "[GOAL-SYNTH] %s → %d weekly tasks (themes=%s)",
        parent_goal.goal_id,
        len(created_ids),
        plan.get("themes", []),
    )
    return {
        "status": "ok",
        "parent_goal_id": parent_goal.goal_id,
        "weekly_goals_created": created_ids,
        "weekly_count": len(created_ids),
        "themes": plan.get("themes", []),
        "raw_response": None,
    }
