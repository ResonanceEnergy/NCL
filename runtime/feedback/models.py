"""Pydantic models for feedback reports. See feedback-synthesis/SCHEMA.md."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# BRS/AAC retired 2026-05-23 — only NCC is a live feedback source.
PillarName = Literal["NCC"]
ReportType = Literal["execution", "revenue", "capital", "health"]
Outcome = Literal["success", "partial", "failed", "blocked"]


class FeedbackReport(BaseModel):
    """Inbound report from a pillar. Strict schema; reports failing
    validation are quarantined."""

    schema_version: str = Field(default="1.0")
    report_id: str = Field(..., min_length=1)
    pillar: PillarName
    report_type: ReportType
    mandate_id: Optional[str] = None
    timestamp: datetime
    summary: str = Field(..., min_length=1, max_length=500)
    outcome: Outcome
    metrics: dict[str, Any] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    next_action_request: Optional[str] = None


class SynthesisNote(BaseModel):
    """Synthesis cortex output — consumed by council/mandate generation."""

    synthesis_id: str
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    reports_consumed: int
    by_pillar: dict[str, int]
    by_outcome: dict[str, int]
    open_blockers: list[dict[str, str]]  # [{pillar, blocker, mandate_id}]
    suggested_adjustments: list[str]
    raw_report_ids: list[str]
