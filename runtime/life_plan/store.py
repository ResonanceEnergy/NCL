"""JSONL-backed Life Plan store.

Append-only writes for goals/journeys/plans; single-file overwrites for
vision/north-star. Reads load + dedup by id (last-write-wins). Small
dataset (dozens of records per type) so no indexing yet.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    Goal,
    Journey,
    NorthStar,
    Plan,
    Vision,
)

log = logging.getLogger("ncl.life_plan.store")


def _root() -> Path:
    base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    return base / "data" / "life_plan"


class LifePlanStore:
    """All-in-one store for the Life Plan subsystem."""

    def __init__(self):
        self.root = _root()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "north-star").mkdir(parents=True, exist_ok=True)
        (self.root / "history").mkdir(parents=True, exist_ok=True)

    # ── Path helpers ────────────────────────────────────────────────────

    @property
    def vision_file(self) -> Path:
        return self.root / "vision.json"

    @property
    def vision_history(self) -> Path:
        return self.root / "history" / "vision-history.jsonl"

    def north_star_file(self, year: int) -> Path:
        return self.root / "north-star" / f"{year}.json"

    @property
    def goals_file(self) -> Path:
        return self.root / "goals.jsonl"

    @property
    def journeys_file(self) -> Path:
        return self.root / "journeys.jsonl"

    @property
    def plans_file(self) -> Path:
        return self.root / "plans.jsonl"

    # ── Atomic file helpers ────────────────────────────────────────────

    @staticmethod
    def _atomic_write(target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(target))

    @staticmethod
    def _append_jsonl(target: Path, obj: dict) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, default=str) + "\n")

    @staticmethod
    def _load_jsonl_dedup(target: Path, id_field: str) -> list[dict]:
        if not target.exists():
            return []
        seen: dict[str, dict] = {}
        with target.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    key = obj.get(id_field, "")
                    if key:
                        seen[key] = obj
                except Exception:
                    continue
        return list(seen.values())

    # ── Vision ──────────────────────────────────────────────────────────

    def get_vision(self) -> Optional[Vision]:
        if not self.vision_file.exists():
            return None
        try:
            return Vision.model_validate_json(self.vision_file.read_text())
        except Exception as e:
            log.warning("[LIFE-PLAN] vision parse failed: %s", e)
            return None

    def save_vision(self, vision: Vision) -> Vision:
        # Archive prior version
        prior = self.get_vision()
        if prior is not None:
            self._append_jsonl(self.vision_history, prior.model_dump(mode="json"))
        vision.active = True
        self._atomic_write(self.vision_file, vision.model_dump_json(indent=2))
        return vision

    def get_vision_history(self) -> list[dict]:
        if not self.vision_history.exists():
            return []
        out: list[dict] = []
        with self.vision_history.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    # ── North Star ──────────────────────────────────────────────────────

    def get_north_star(self, year: int) -> Optional[NorthStar]:
        f = self.north_star_file(year)
        if not f.exists():
            return None
        try:
            return NorthStar.model_validate_json(f.read_text())
        except Exception as e:
            log.warning("[LIFE-PLAN] north-star %s parse failed: %s", year, e)
            return None

    def save_north_star(self, star: NorthStar) -> NorthStar:
        self._atomic_write(self.north_star_file(star.year), star.model_dump_json(indent=2))
        return star

    def get_current_north_star(self) -> Optional[NorthStar]:
        return self.get_north_star(datetime.now(timezone.utc).year)

    # ── Goals ───────────────────────────────────────────────────────────

    def save_goal(self, goal: Goal) -> Goal:
        goal.last_updated = datetime.now(timezone.utc)
        self._append_jsonl(self.goals_file, goal.model_dump(mode="json"))
        return goal

    def list_goals(
        self,
        *,
        scope: Optional[str] = None,
        status: Optional[str] = None,
        parent_goal_id: Optional[str] = None,
    ) -> list[Goal]:
        raw = self._load_jsonl_dedup(self.goals_file, "goal_id")
        goals: list[Goal] = []
        for r in raw:
            try:
                g = Goal.model_validate(r)
            except Exception:
                continue
            if scope and g.scope != scope:
                continue
            if status and g.status != status:
                continue
            if parent_goal_id and g.parent_goal_id != parent_goal_id:
                continue
            goals.append(g)
        # Newest first
        goals.sort(key=lambda g: g.last_updated, reverse=True)
        return goals

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        for g in self.list_goals():
            if g.goal_id == goal_id:
                return g
        return None

    # ── Journeys ────────────────────────────────────────────────────────

    def save_journey(self, journey: Journey) -> Journey:
        self._append_jsonl(self.journeys_file, journey.model_dump(mode="json"))
        return journey

    def list_journeys(self, *, status: Optional[str] = None) -> list[Journey]:
        raw = self._load_jsonl_dedup(self.journeys_file, "journey_id")
        out: list[Journey] = []
        for r in raw:
            try:
                j = Journey.model_validate(r)
            except Exception:
                continue
            if status and j.status != status:
                continue
            out.append(j)
        out.sort(key=lambda j: j.started_at, reverse=True)
        return out

    def get_journey(self, journey_id: str) -> Optional[Journey]:
        for j in self.list_journeys():
            if j.journey_id == journey_id:
                return j
        return None

    def complete_milestone(self, journey_id: str, milestone_id: str, reflection: str = "") -> Optional[Journey]:
        j = self.get_journey(journey_id)
        if j is None:
            return None
        updated = False
        for m in j.milestones:
            if m.milestone_id == milestone_id:
                m.completed_at = datetime.now(timezone.utc)
                if reflection:
                    m.reflection = reflection
                updated = True
                break
        if updated:
            self.save_journey(j)
        return j if updated else None

    # ── Plans ───────────────────────────────────────────────────────────

    def save_plan(self, plan: Plan) -> Plan:
        plan.last_updated = datetime.now(timezone.utc)
        self._append_jsonl(self.plans_file, plan.model_dump(mode="json"))
        return plan

    def list_plans(self, *, kind: Optional[str] = None, status: Optional[str] = None) -> list[Plan]:
        raw = self._load_jsonl_dedup(self.plans_file, "plan_id")
        out: list[Plan] = []
        for r in raw:
            try:
                p = Plan.model_validate(r)
            except Exception:
                continue
            if kind and p.kind != kind:
                continue
            if status and p.status != status:
                continue
            out.append(p)
        out.sort(key=lambda p: (p.target_date or _date.max), reverse=False)
        return out

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        for p in self.list_plans():
            if p.plan_id == plan_id:
                return p
        return None

    def toggle_checklist_item(self, plan_id: str, item_id: str) -> Optional[Plan]:
        p = self.get_plan(plan_id)
        if p is None:
            return None
        for item in p.checklist:
            if item.item_id == item_id:
                item.done = not item.done
                item.completed_at = datetime.now(timezone.utc) if item.done else None
                self.save_plan(p)
                return p
        return None

    # ── Dashboard rollup ────────────────────────────────────────────────

    def dashboard(self) -> dict:
        """One-shot rollup for iOS Life Plan home screen."""
        return {
            "vision": (self.get_vision().model_dump(mode="json") if self.get_vision() else None),
            "north_star": (
                self.get_current_north_star().model_dump(mode="json")
                if self.get_current_north_star()
                else None
            ),
            "active_goals_count": len(self.list_goals(status="active")),
            "active_journeys_count": len(self.list_journeys(status="active")),
            "planning_plans_count": len(self.list_plans(status="planning")),
            "active_plans_count": len(self.list_plans(status="active")),
        }
