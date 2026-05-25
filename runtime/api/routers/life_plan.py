"""Life Plan endpoints — Wave 14E (2026-05-25).

Vision / North Star / Goals (OKR) / Journeys / Plans (vacation/project/
retirement) / Daily Wisdom rotation. All gated by verify_strike_token_dep.

See docs/JOURNAL_REDESIGN_2026-05-25.md for design rationale.
"""

from __future__ import annotations  # noqa: I001

import logging
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..deps import verify_strike_token_dep
from ...life_plan import (
    Goal,
    Journey,
    Milestone,
    NorthStar,
    Plan,
    Vision,
    LifePlanStore,
    WisdomRotator,
)
from ...life_plan.models import ChecklistItem, KeyResult

log = logging.getLogger(__name__)

router = APIRouter(tags=["life-plan"])


# Module-level singletons (cheap; no LLM dependencies)
_store = LifePlanStore()
_wisdom = WisdomRotator()


# ── Request schemas ──────────────────────────────────────────────────────


class _VisionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    narrative: str = ""
    horizon_years: int = 10
    pillars: list[str] = Field(default_factory=list)


class _NorthStarRequest(BaseModel):
    year: int
    title: str
    measurable: str = ""
    why: str = ""


class _KeyResultIn(BaseModel):
    description: str
    target: float
    current: float = 0.0
    unit: str = ""


class _GoalRequest(BaseModel):
    scope: str = "quarter"
    objective: str
    key_results: list[_KeyResultIn] = Field(default_factory=list)
    parent_goal_id: Optional[str] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    status: str = "active"
    confidence: int = 7


class _GoalUpdate(BaseModel):
    objective: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[int] = None
    kr_updates: list[dict] = Field(default_factory=list)  # [{kr_id, current}]


class _MilestoneIn(BaseModel):
    title: str
    target_at: Optional[str] = None


class _JourneyRequest(BaseModel):
    title: str
    narrative: str = ""
    started_at: Optional[str] = None
    expected_end_at: Optional[str] = None
    milestones: list[_MilestoneIn] = Field(default_factory=list)
    status: str = "active"


class _ChecklistItemIn(BaseModel):
    text: str
    due_at: Optional[str] = None


class _PlanRequest(BaseModel):
    title: str
    kind: str = "project"
    target_date: Optional[str] = None
    budget_usd: Optional[float] = None
    checklist: list[_ChecklistItemIn] = Field(default_factory=list)
    narrative: str = ""
    status: str = "planning"


class _WisdomRequest(BaseModel):
    id: str
    category: str = "stoic"
    text: str
    source: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse_date(s: Optional[str]) -> Optional[_date]:
    if not s:
        return None
    try:
        return _date.fromisoformat(s)
    except Exception:
        return None


# ── Vision ───────────────────────────────────────────────────────────────


@router.post("/life/vision")
async def set_vision(body: _VisionRequest, _: None = Depends(verify_strike_token_dep)) -> dict:
    v = Vision(
        title=body.title,
        narrative=body.narrative,
        horizon_years=body.horizon_years,
        pillars=body.pillars,
    )
    saved = _store.save_vision(v)
    return {"status": "ok", "vision": saved.model_dump(mode="json")}


@router.get("/life/vision")
async def get_vision(_: None = Depends(verify_strike_token_dep)) -> dict:
    v = _store.get_vision()
    if not v:
        return {"status": "not_set", "vision": None}
    return {"status": "ok", "vision": v.model_dump(mode="json")}


@router.get("/life/vision/history")
async def get_vision_history(_: None = Depends(verify_strike_token_dep)) -> dict:
    return {"status": "ok", "items": _store.get_vision_history()}


# ── North Star ───────────────────────────────────────────────────────────


@router.post("/life/north-star")
async def set_north_star(body: _NorthStarRequest, _: None = Depends(verify_strike_token_dep)) -> dict:
    ns = NorthStar(year=body.year, title=body.title, measurable=body.measurable, why=body.why)
    saved = _store.save_north_star(ns)
    return {"status": "ok", "north_star": saved.model_dump(mode="json")}


@router.get("/life/north-star/current")
async def get_current_north_star(_: None = Depends(verify_strike_token_dep)) -> dict:
    ns = _store.get_current_north_star()
    if not ns:
        return {"status": "not_set", "north_star": None}
    return {"status": "ok", "north_star": ns.model_dump(mode="json")}


@router.get("/life/north-star/{year}")
async def get_north_star_year(year: int, _: None = Depends(verify_strike_token_dep)) -> dict:
    ns = _store.get_north_star(year)
    if not ns:
        return {"status": "not_set", "year": year, "north_star": None}
    return {"status": "ok", "north_star": ns.model_dump(mode="json")}


# ── Goals ────────────────────────────────────────────────────────────────


@router.post("/life/goal")
async def create_goal(body: _GoalRequest, _: None = Depends(verify_strike_token_dep)) -> dict:
    g = Goal(
        scope=body.scope,
        objective=body.objective,
        key_results=[KeyResult(**kr.model_dump()) for kr in body.key_results],
        parent_goal_id=body.parent_goal_id,
        starts_at=_parse_date(body.starts_at) or _date.today(),
        ends_at=_parse_date(body.ends_at) or _date.today(),
        status=body.status,
        confidence=body.confidence,
    )
    saved = _store.save_goal(g)
    return {"status": "ok", "goal": saved.model_dump(mode="json")}


@router.get("/life/goals")
async def list_goals(
    scope: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    parent_goal_id: Optional[str] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    goals = _store.list_goals(scope=scope, status=status, parent_goal_id=parent_goal_id)
    return {
        "status": "ok",
        "count": len(goals),
        "goals": [g.model_dump(mode="json") for g in goals],
    }


@router.get("/life/goal/{goal_id}")
async def get_goal(goal_id: str, _: None = Depends(verify_strike_token_dep)) -> dict:
    g = _store.get_goal(goal_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"goal {goal_id} not found")
    return {"status": "ok", "goal": g.model_dump(mode="json")}


@router.patch("/life/goal/{goal_id}")
async def update_goal(goal_id: str, body: _GoalUpdate, _: None = Depends(verify_strike_token_dep)) -> dict:
    g = _store.get_goal(goal_id)
    if not g:
        raise HTTPException(status_code=404, detail=f"goal {goal_id} not found")
    if body.objective is not None:
        g.objective = body.objective
    if body.status is not None:
        g.status = body.status
    if body.confidence is not None:
        g.confidence = max(1, min(10, body.confidence))
    # KR updates
    for upd in body.kr_updates:
        kr_id = upd.get("kr_id")
        current = upd.get("current")
        if kr_id is None or current is None:
            continue
        for kr in g.key_results:
            if kr.kr_id == kr_id:
                try:
                    kr.current = float(current)
                except (TypeError, ValueError):
                    pass
    saved = _store.save_goal(g)
    return {"status": "ok", "goal": saved.model_dump(mode="json")}


# ── Journeys ─────────────────────────────────────────────────────────────


@router.post("/life/journey")
async def create_journey(body: _JourneyRequest, _: None = Depends(verify_strike_token_dep)) -> dict:
    j = Journey(
        title=body.title,
        narrative=body.narrative,
        started_at=_parse_date(body.started_at) or _date.today(),
        expected_end_at=_parse_date(body.expected_end_at),
        milestones=[
            Milestone(title=m.title, target_at=_parse_date(m.target_at)) for m in body.milestones
        ],
        status=body.status,
    )
    saved = _store.save_journey(j)
    return {"status": "ok", "journey": saved.model_dump(mode="json")}


@router.get("/life/journeys")
async def list_journeys(status: Optional[str] = None, _: None = Depends(verify_strike_token_dep)) -> dict:
    items = _store.list_journeys(status=status)
    return {
        "status": "ok",
        "count": len(items),
        "journeys": [j.model_dump(mode="json") for j in items],
    }


@router.get("/life/journey/{journey_id}")
async def get_journey(journey_id: str, _: None = Depends(verify_strike_token_dep)) -> dict:
    j = _store.get_journey(journey_id)
    if not j:
        raise HTTPException(status_code=404, detail=f"journey {journey_id} not found")
    return {"status": "ok", "journey": j.model_dump(mode="json")}


@router.patch("/life/journey/{journey_id}/milestone/{milestone_id}")
async def complete_milestone(
    journey_id: str,
    milestone_id: str,
    reflection: str = Query(default=""),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    j = _store.complete_milestone(journey_id, milestone_id, reflection=reflection)
    if not j:
        raise HTTPException(status_code=404, detail="journey or milestone not found")
    return {"status": "ok", "journey": j.model_dump(mode="json")}


# ── Plans ────────────────────────────────────────────────────────────────


@router.post("/life/plan")
async def create_plan(body: _PlanRequest, _: None = Depends(verify_strike_token_dep)) -> dict:
    p = Plan(
        title=body.title,
        kind=body.kind,
        target_date=_parse_date(body.target_date),
        budget_usd=body.budget_usd,
        checklist=[ChecklistItem(text=c.text, due_at=_parse_date(c.due_at)) for c in body.checklist],
        narrative=body.narrative,
        status=body.status,
    )
    saved = _store.save_plan(p)
    return {"status": "ok", "plan": saved.model_dump(mode="json")}


@router.get("/life/plans")
async def list_plans(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    items = _store.list_plans(kind=kind, status=status)
    return {
        "status": "ok",
        "count": len(items),
        "plans": [p.model_dump(mode="json") for p in items],
    }


@router.get("/life/plan/{plan_id}")
async def get_plan(plan_id: str, _: None = Depends(verify_strike_token_dep)) -> dict:
    p = _store.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"plan {plan_id} not found")
    return {"status": "ok", "plan": p.model_dump(mode="json")}


@router.patch("/life/plan/{plan_id}/checklist/{item_id}")
async def toggle_checklist(plan_id: str, item_id: str, _: None = Depends(verify_strike_token_dep)) -> dict:
    p = _store.toggle_checklist_item(plan_id, item_id)
    if not p:
        raise HTTPException(status_code=404, detail="plan or item not found")
    return {"status": "ok", "plan": p.model_dump(mode="json")}


# ── Daily Wisdom ─────────────────────────────────────────────────────────


@router.get("/life/wisdom/today")
async def get_wisdom_today(
    category: Optional[str] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    w = _wisdom.today(category=category)
    if not w:
        return {"status": "empty", "wisdom": None}
    return {"status": "ok", "wisdom": w.model_dump(mode="json")}


@router.get("/life/wisdom/category/{category}")
async def get_wisdom_category(category: str, _: None = Depends(verify_strike_token_dep)) -> dict:
    items = _wisdom.list_category(category)
    return {
        "status": "ok",
        "category": category,
        "count": len(items),
        "items": [w.model_dump(mode="json") for w in items],
    }


@router.get("/life/wisdom/categories")
async def list_wisdom_categories(_: None = Depends(verify_strike_token_dep)) -> dict:
    return {"status": "ok", "categories": _wisdom.list_categories()}


@router.post("/life/wisdom")
async def add_wisdom(body: _WisdomRequest, _: None = Depends(verify_strike_token_dep)) -> dict:
    """Append a new wisdom to the corpus (idempotent on id)."""
    import json
    from ...life_plan.wisdom import _wisdom_file

    f = _wisdom_file()
    # Read existing ids to avoid duplicates
    existing_ids: set[str] = set()
    if f.exists():
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    if obj.get("id"):
                        existing_ids.add(obj["id"])
                except Exception:
                    continue
    if body.id in existing_ids:
        return {"status": "exists", "id": body.id}
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(body.model_dump()) + "\n")
    return {"status": "added", "id": body.id}


# ── Dashboard rollup ─────────────────────────────────────────────────────


@router.get("/life/dashboard")
async def life_dashboard(_: None = Depends(verify_strike_token_dep)) -> dict:
    """One-shot rollup powering the iOS Life Plan home screen."""
    db = _store.dashboard()
    db["wisdom_today"] = None
    try:
        w = _wisdom.today()
        if w:
            db["wisdom_today"] = w.model_dump(mode="json")
    except Exception:
        pass
    return {"status": "ok", **db}
