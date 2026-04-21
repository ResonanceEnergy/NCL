"""
BIT RAGE LABOUR SYSTEMS — Semi-Autonomous Pipeline
www.bit-rage-labour.com | sales@bit-rage-labour.com
"AI Agents That Bite Back" — Resonance Energy

Implements Jake Van Clief's Model Workspace Protocol (MWP) for staged,
traceable mandate processing through the BIT RAGE LABOUR agent fleet.

The pipeline is driven by BRS (Bit Rage Systems) internals — agent fleet
dispatch, revenue operations, and outcome-based task routing. NOT by
intelligence signals. BRL agents handle the work autonomously:
  - Sales Ops ($2.40/lead, 12s delivery)
  - Support Resolver ($1.00/ticket)
  - Content Repurposer ($3/piece)
  - Document Extractor ($1.50/doc)
  + 26 additional specialist agents

Architecture (Van Clief ICM / MWP):
  ┌─────────────────────────────────────────────────────────┐
  │  STAGE 1: INTAKE          Mandate arrives, validated    │
  │  STAGE 2: ANALYSIS        Route to BRL agent, risk scored│
  │  STAGE 3: EXECUTION       BRL agent dispatched          │
  │  STAGE 4: REVIEW          QA + cost tracking            │
  │  STAGE 5: OUTPUT          Results filed, Paperclip closed│
  └─────────────────────────────────────────────────────────┘

Semi-Autonomous Gates (Paperclip-governed):
  - LOW risk (score ≤ 30):   Auto-execute, log to Paperclip
  - MEDIUM risk (31-60):     Auto-execute, notify NATRIX
  - HIGH risk (61-80):       Queue for approval, notify
  - CRITICAL risk (81-100):  Hard stop, require explicit approval

Usage:
    from runtime.autonomous.dl_pipeline import DLPipeline

    pipeline = DLPipeline(paperclip=paperclip_client, dl_bridge=dl_bridge)
    await pipeline.start()

    # Submit mandate for processing
    await pipeline.submit_mandate(mandate_dict)

    # Check pipeline status
    status = pipeline.get_status()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ncl.brl_pipeline")

# ── Configuration ───────────────────────────────────────────────────────
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
MWP_WORKSPACE = "execution-pipeline"
MWP_STAGES = ["01-Input", "02-Planning", "03-Execution", "04-Review", "05-Output"]

# Semi-autonomous thresholds
RISK_AUTO_EXECUTE = 30       # ≤ 30: auto-execute silently
RISK_AUTO_NOTIFY = 60        # 31-60: auto-execute + notify
RISK_REQUIRE_APPROVAL = 80   # 61-80: hold for approval
# > 80: CRITICAL — hard stop

# Pipeline loop interval (seconds)
PIPELINE_INTERVAL = 30
FLEET_HEALTH_INTERVAL = 300  # 5 minutes


class MandateStage(str, Enum):
    """MWP stage lifecycle for a mandate."""
    INTAKE = "intake"
    ANALYSIS = "analysis"
    EXECUTION = "execution"
    REVIEW = "review"
    OUTPUT = "output"
    BLOCKED = "blocked"        # Waiting for approval
    FAILED = "failed"
    COMPLETED = "completed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Risk Keywords ───────────────────────────────────────────────────────
# Used for risk scoring mandates before auto-dispatch
RISK_ESCALATORS = {
    # Financial actions → high risk
    "trade": 40, "purchase": 35, "payment": 40, "invoice": 30,
    "transfer": 45, "withdraw": 50, "spend": 30, "budget": 20,
    # External comms → medium risk
    "email": 20, "outreach": 25, "cold_email": 30, "publish": 25,
    "social_media": 20, "press_release": 25, "ad_copy": 15,
    # Data operations → low risk
    "research": 5, "analysis": 5, "report": 10, "summary": 5,
    "data_entry": 10, "scraping": 15, "documentation": 5,
    # Platform actions → medium risk
    "upwork": 25, "fiverr": 25, "freelance": 20, "bid": 30,
    "proposal": 15, "deliver": 20,
    # System operations → variable
    "nerve": 35, "restart": 30, "pause": 15, "resume": 10,
}

# Agent → base risk (some agents are inherently riskier)
AGENT_BASE_RISK = {
    # Sales (outbound = higher risk)
    "sales_outreach": 30, "lead_gen": 20, "email_marketing": 30, "proposal_writer": 15,
    # Content (low risk, internal production)
    "content_repurpose": 10, "seo_content": 10, "social_media": 20,
    "press_release": 20, "ad_copy": 15, "product_desc": 10,
    "resume_writer": 10, "tech_docs": 5,
    # Research
    "market_research": 5, "business_plan": 10, "ops_brief": 5,
    # Operations
    "support_ticket": 15, "data_entry": 10, "bookkeeping": 25,
    "crm_ops": 15, "web_scraper": 15, "doc_extract": 10,
    # Infrastructure (internal, low risk)
    "context_manager": 5, "qa_manager": 5, "production_manager": 5, "automation_manager": 10,
    # Freelance platforms (external = higher risk)
    "freelancer_work": 25, "upwork_work": 30, "fiverr_work": 30, "pph_work": 25, "guru_work": 25,
}


# ── Pipeline Item ───────────────────────────────────────────────────────

class PipelineItem:
    """A single mandate flowing through the DL pipeline."""

    def __init__(self, mandate: dict):
        self.id = mandate.get("mandate_id") or f"dl-{uuid.uuid4().hex[:8]}"
        self.mandate = mandate
        self.stage = MandateStage.INTAKE
        self.risk_score: int = 0
        self.risk_level: RiskLevel = RiskLevel.LOW
        self.target_agent: str = ""
        self.paperclip_issue_id: str = ""
        self.dispatch_result: dict = {}
        self.review_notes: str = ""
        self.cost_cents: int = 0
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at
        self.stage_history: list[dict] = []
        self.approval_requested: bool = False
        self.approved: bool = False

    def advance(self, new_stage: MandateStage, notes: str = "") -> None:
        """Move item to next stage with audit trail."""
        self.stage_history.append({
            "from": self.stage.value,
            "to": new_stage.value,
            "at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        })
        self.stage = new_stage
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stage": self.stage.value,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "target_agent": self.target_agent,
            "paperclip_issue_id": self.paperclip_issue_id,
            "mandate_title": self.mandate.get("title", ""),
            "mandate_pillar": self.mandate.get("pillar", ""),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "stage_history": self.stage_history,
            "cost_cents": self.cost_cents,
            "approved": self.approved,
        }


# ── DL Pipeline Orchestrator ───────────────────────────────────────────

class DLPipeline:
    """
    BIT RAGE LABOUR SYSTEMS — Semi-autonomous pipeline.
    Paperclip governance + Van Clief MWP stage processing.
    Driven by BRS internals, not intelligence signals.
    www.bit-rage-labour.com | sales@bit-rage-labour.com
    """

    def __init__(
        self,
        paperclip=None,
        dl_bridge=None,
        ncl_base: Path = NCL_BASE,
        notify_fn=None,
    ):
        """
        Args:
            paperclip: PaperclipClient instance for governance
            dl_bridge: DigitalLabourBridge instance for agent dispatch
            ncl_base: NCL base directory for MWP workspace artifacts
            notify_fn: async callable(title, body, priority) for push notifications
        """
        self.paperclip = paperclip
        self.dl_bridge = dl_bridge
        self.ncl_base = ncl_base
        self.notify_fn = notify_fn

        # Pipeline state
        self._queue: list[PipelineItem] = []           # Intake queue
        self._active: dict[str, PipelineItem] = {}     # In-flight items
        self._completed: list[PipelineItem] = []       # Done (last 50)
        self._blocked: dict[str, PipelineItem] = {}    # Waiting approval

        # MWP workspace paths
        self._mwp_base = ncl_base / "workspaces" / MWP_WORKSPACE
        self._stages_dir = {
            s: self._mwp_base / s for s in MWP_STAGES
        }

        # Stats
        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_blocked": 0,
            "total_auto_executed": 0,
            "total_cost_cents": 0,
            "started_at": None,
        }

        # Background task handle
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._last_fleet_status: dict = {}

        logger.info("BIT RAGE LABOUR pipeline initialized (MWP workspace: %s)", MWP_WORKSPACE)

    # ── Public API ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the pipeline processing loop."""
        if self._running:
            return
        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()
        self._task = asyncio.create_task(self._pipeline_loop(), name="ncl-dl-pipeline")
        self._health_task = asyncio.create_task(self._fleet_health_loop(), name="ncl-dl-health")
        logger.info("BIT RAGE LABOUR pipeline started (interval: %ds)", PIPELINE_INTERVAL)

    async def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False
        for t in [self._task, self._health_task]:
            if t:
                t.cancel()
        self._task = None
        self._health_task = None
        logger.info("BIT RAGE LABOUR pipeline stopped")

    async def submit_mandate(self, mandate: dict) -> dict:
        """
        Submit a mandate for semi-autonomous processing.

        Returns dict with item ID and initial assessment.
        """
        item = PipelineItem(mandate)
        self._queue.append(item)
        self._stats["total_submitted"] += 1

        logger.info(
            "[BRL] Mandate submitted: %s — '%s'",
            item.id, mandate.get("title", "untitled")
        )

        # Write artifact to MWP Stage 1 (Input)
        await self._write_mwp_artifact("01-Input", item.id, {
            "mandate": mandate,
            "submitted_at": item.created_at.isoformat(),
        })

        return {
            "item_id": item.id,
            "status": "queued",
            "queue_position": len(self._queue),
        }

    async def approve_item(self, item_id: str) -> dict:
        """Approve a blocked item for execution."""
        item = self._blocked.pop(item_id, None)
        if not item:
            return {"error": f"Item {item_id} not found in blocked queue"}

        item.approved = True
        item.advance(MandateStage.EXECUTION, "Approved by NATRIX")
        self._active[item.id] = item

        logger.info("[BRL] Item %s approved — advancing to execution", item_id)

        # Update Paperclip
        if self.paperclip and item.paperclip_issue_id:
            try:
                await self.paperclip.update_mandate_status(item.id, "in_progress", "Approved for execution")
            except Exception as e:
                logger.warning("[BRL] Paperclip update failed: %s", e)

        return {"item_id": item_id, "status": "approved", "stage": "execution"}

    async def reject_item(self, item_id: str, reason: str = "") -> dict:
        """Reject a blocked item."""
        item = self._blocked.pop(item_id, None)
        if not item:
            return {"error": f"Item {item_id} not found in blocked queue"}

        item.advance(MandateStage.FAILED, f"Rejected: {reason}")
        self._completed.append(item)
        self._stats["total_failed"] += 1

        logger.info("[BRL] Item %s rejected: %s", item_id, reason)

        if self.paperclip and item.paperclip_issue_id:
            try:
                await self.paperclip.update_mandate_status(item.id, "closed", f"Rejected: {reason}")
            except Exception as e:
                logger.warning("[BRL] Paperclip close failed: %s", e)

        return {"item_id": item_id, "status": "rejected"}

    def get_status(self) -> dict:
        """Get full pipeline status."""
        return {
            "running": self._running,
            "stats": self._stats,
            "queue": [i.to_dict() for i in self._queue],
            "active": {k: v.to_dict() for k, v in self._active.items()},
            "blocked": {k: v.to_dict() for k, v in self._blocked.items()},
            "completed_recent": [i.to_dict() for i in self._completed[-10:]],
            "fleet_status": self._last_fleet_status,
        }

    def get_blocked_items(self) -> list[dict]:
        """Get items waiting for approval."""
        return [v.to_dict() for v in self._blocked.values()]

    # ── Pipeline Loop ───────────────────────────────────────────────

    async def _pipeline_loop(self) -> None:
        """Main processing loop — processes queue through MWP stages."""
        logger.info("[BRL] Pipeline loop started")
        while self._running:
            try:
                await self._process_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[BRL] Pipeline cycle error: %s", e, exc_info=True)
            await asyncio.sleep(PIPELINE_INTERVAL)

    async def _process_cycle(self) -> None:
        """Single pipeline processing cycle."""

        # 1. Intake: move queued items to active
        while self._queue:
            item = self._queue.pop(0)
            item.advance(MandateStage.ANALYSIS, "Moved to analysis")
            self._active[item.id] = item

        # 2. Process each active item through its current stage
        completed_ids = []
        for item_id, item in list(self._active.items()):
            try:
                if item.stage == MandateStage.ANALYSIS:
                    await self._stage_analysis(item)
                elif item.stage == MandateStage.EXECUTION:
                    await self._stage_execution(item)
                elif item.stage == MandateStage.REVIEW:
                    await self._stage_review(item)
                elif item.stage == MandateStage.OUTPUT:
                    await self._stage_output(item)
                    completed_ids.append(item_id)
                elif item.stage == MandateStage.COMPLETED:
                    completed_ids.append(item_id)
                elif item.stage == MandateStage.FAILED:
                    completed_ids.append(item_id)
            except Exception as e:
                logger.error("[BRL] Stage error for %s: %s", item_id, e)
                item.advance(MandateStage.FAILED, str(e))
                completed_ids.append(item_id)

        # 3. Move completed/failed to history
        for cid in completed_ids:
            item = self._active.pop(cid, None)
            if item:
                self._completed.append(item)
                if len(self._completed) > 50:
                    self._completed = self._completed[-50:]

    # ── Stage Processors (Van Clief MWP) ────────────────────────────

    async def _stage_analysis(self, item: PipelineItem) -> None:
        """
        STAGE 2: ANALYSIS
        - Score risk level
        - Determine target DL agent
        - Register in Paperclip
        - Gate decision: auto-execute vs hold for approval
        """
        mandate = item.mandate
        title = (mandate.get("title", "") + " " + mandate.get("objective", "")).lower()
        pillar = mandate.get("pillar", "").lower()

        # ── Risk scoring ──
        risk = 0

        # Keyword-based risk
        for keyword, score in RISK_ESCALATORS.items():
            if keyword in title or keyword in pillar:
                risk = max(risk, score)

        # Priority multiplier (high priority = higher risk)
        priority = mandate.get("priority", 5)
        if priority <= 2:
            risk = int(risk * 1.3)
        elif priority >= 8:
            risk = int(risk * 0.8)

        # Budget-related (if mandate has cost estimate)
        estimated_cost = mandate.get("estimated_cost_cents", 0)
        if estimated_cost > 5000:    # > $50
            risk += 20
        elif estimated_cost > 1000:  # > $10
            risk += 10

        risk = min(risk, 100)
        item.risk_score = risk

        # ── Risk level classification ──
        if risk <= RISK_AUTO_EXECUTE:
            item.risk_level = RiskLevel.LOW
        elif risk <= RISK_AUTO_NOTIFY:
            item.risk_level = RiskLevel.MEDIUM
        elif risk <= RISK_REQUIRE_APPROVAL:
            item.risk_level = RiskLevel.HIGH
        else:
            item.risk_level = RiskLevel.CRITICAL

        # ── Agent routing ──
        item.target_agent = self._route_to_agent(mandate)

        # Add agent base risk
        agent_risk = AGENT_BASE_RISK.get(item.target_agent, 15)
        item.risk_score = min(100, item.risk_score + agent_risk // 2)

        # ── Register in Paperclip ──
        if self.paperclip:
            try:
                issue_id = await self.paperclip.create_mandate_as_issue(
                    mandate_id=item.id,
                    pillar=mandate.get("pillar", "BRS"),
                    title=mandate.get("title", "DL Task"),
                    objective=mandate.get("objective", ""),
                    priority="critical" if risk > 80 else "high" if risk > 60 else "medium" if risk > 30 else "low",
                    success_criteria=mandate.get("success_criteria", []),
                )
                item.paperclip_issue_id = issue_id
            except Exception as e:
                logger.warning("[BRL] Paperclip issue creation failed: %s", e)

        # ── Write analysis artifact to MWP Stage 2 ──
        await self._write_mwp_artifact("02-Planning", item.id, {
            "risk_score": item.risk_score,
            "risk_level": item.risk_level.value,
            "target_agent": item.target_agent,
            "paperclip_issue_id": item.paperclip_issue_id,
            "gate_decision": "auto" if risk <= RISK_AUTO_NOTIFY else "approval_required",
        })

        # ── Gate Decision ──
        if item.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
            # Auto-execute
            item.advance(MandateStage.EXECUTION, f"Auto-approved (risk={risk}, level={item.risk_level.value})")
            self._stats["total_auto_executed"] += 1

            if item.risk_level == RiskLevel.MEDIUM and self.notify_fn:
                await self._notify(
                    f"⚡ BRL Auto-Dispatch: {mandate.get('title', 'Task')[:50]}",
                    f"Agent: {item.target_agent}\nRisk: {risk}/100 ({item.risk_level.value})\nAuto-executing...",
                    priority=3,
                )

            logger.info(
                "[BRL] %s auto-approved (risk=%d, agent=%s)",
                item.id, risk, item.target_agent,
            )

        elif item.risk_level == RiskLevel.HIGH:
            # Hold for approval
            item.advance(MandateStage.BLOCKED, f"Held for approval (risk={risk})")
            item.approval_requested = True
            self._active.pop(item.id, None)
            self._blocked[item.id] = item
            self._stats["total_blocked"] += 1

            if self.notify_fn:
                await self._notify(
                    f"🔒 BRL Approval Needed: {mandate.get('title', 'Task')[:50]}",
                    f"Agent: {item.target_agent}\nRisk: {risk}/100 (HIGH)\nApprove in Command Center.",
                    priority=4,
                )

            logger.info("[BRL] %s BLOCKED — requires approval (risk=%d)", item.id, risk)

        else:
            # CRITICAL — hard stop
            item.advance(MandateStage.BLOCKED, f"CRITICAL risk ({risk}) — hard stop")
            item.approval_requested = True
            self._active.pop(item.id, None)
            self._blocked[item.id] = item
            self._stats["total_blocked"] += 1

            if self.notify_fn:
                await self._notify(
                    f"🚨 CRITICAL: BRL Task Blocked: {mandate.get('title', 'Task')[:50]}",
                    f"Agent: {item.target_agent}\nRisk: {risk}/100 (CRITICAL)\nManual review required.",
                    priority=5,
                )

            logger.warning("[BRL] %s CRITICAL BLOCK (risk=%d)", item.id, risk)

    async def _stage_execution(self, item: PipelineItem) -> None:
        """
        STAGE 3: EXECUTION
        - Dispatch task to Digital Labour agent
        - Track result
        """
        if not self.dl_bridge:
            item.advance(MandateStage.FAILED, "DL bridge not available")
            self._stats["total_failed"] += 1
            return

        logger.info(
            "[BRL] Dispatching %s → agent=%s",
            item.id, item.target_agent,
        )

        try:
            result = await self.dl_bridge.dispatch_task(
                agent_type=item.target_agent,
                task_data={
                    "mandate_id": item.id,
                    "title": item.mandate.get("title", ""),
                    "objective": item.mandate.get("objective", ""),
                    "success_criteria": item.mandate.get("success_criteria", []),
                    "context": item.mandate.get("context", {}),
                    "source": "ncl-dl-pipeline",
                },
                priority=item.mandate.get("priority", 5),
            )

            item.dispatch_result = result

            # Write execution artifact to MWP Stage 3
            await self._write_mwp_artifact("03-Execution", item.id, {
                "agent": item.target_agent,
                "dispatch_result": result,
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            })

            # Update Paperclip
            if self.paperclip:
                try:
                    await self.paperclip.update_mandate_status(
                        item.id, "in_progress",
                        f"Dispatched to {item.target_agent}"
                    )
                except Exception as e:
                    logger.warning("[BRL] Paperclip update failed: %s", e)

            # Check dispatch status
            if result.get("status") == "error":
                item.advance(MandateStage.FAILED, f"Dispatch error: {result.get('error', 'unknown')}")
                self._stats["total_failed"] += 1
            else:
                item.advance(MandateStage.REVIEW, "Dispatched successfully")

        except Exception as e:
            logger.error("[BRL] Dispatch failed for %s: %s", item.id, e)
            item.advance(MandateStage.FAILED, str(e))
            self._stats["total_failed"] += 1

    async def _stage_review(self, item: PipelineItem) -> None:
        """
        STAGE 4: REVIEW
        - Validate dispatch result
        - Estimate cost
        - Log to Paperclip
        """
        result = item.dispatch_result

        # Estimate cost based on agent type
        cost_map = {
            "market_research": 50, "sales_ops": 100, "lead_gen": 80,
            "email_marketing": 60, "content_repurpose": 40, "seo_content": 40,
            "social_media": 30, "proposal_writer": 80, "business_plan": 120,
            "web_scraper": 20, "data_entry": 15, "bookkeeping": 40,
        }
        estimated_cost = cost_map.get(item.target_agent, 30)
        item.cost_cents = estimated_cost
        self._stats["total_cost_cents"] += estimated_cost

        # Report cost to Paperclip
        if self.paperclip:
            try:
                await self.paperclip.report_cost(
                    agent_name="NCL",  # Use NCL as the reporting agent
                    model=f"dl-{item.target_agent}",
                    cost_cents=estimated_cost,
                    metadata={
                        "mandate_id": item.id,
                        "agent": item.target_agent,
                        "dispatch_status": result.get("status", "unknown"),
                    },
                )
            except Exception as e:
                logger.warning("[BRL] Cost reporting failed: %s", e)

        # Write review artifact to MWP Stage 4
        await self._write_mwp_artifact("04-Review", item.id, {
            "dispatch_status": result.get("status", "unknown"),
            "estimated_cost_cents": estimated_cost,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })

        item.review_notes = f"Dispatched to {item.target_agent}, est. cost: ${estimated_cost/100:.2f}"
        item.advance(MandateStage.OUTPUT, "Review complete")

    async def _stage_output(self, item: PipelineItem) -> None:
        """
        STAGE 5: OUTPUT
        - Close Paperclip issue
        - Write final artifact
        - Move to completed
        """
        # Close in Paperclip
        if self.paperclip:
            try:
                await self.paperclip.update_mandate_status(
                    item.id, "closed",
                    f"Completed via {item.target_agent} | Cost: ${item.cost_cents/100:.2f}"
                )
            except Exception as e:
                logger.warning("[BRL] Paperclip close failed: %s", e)

        # Write output artifact
        await self._write_mwp_artifact("05-Output", item.id, {
            "mandate_id": item.id,
            "agent": item.target_agent,
            "risk_score": item.risk_score,
            "risk_level": item.risk_level.value,
            "cost_cents": item.cost_cents,
            "auto_executed": not item.approval_requested,
            "dispatch_result": item.dispatch_result,
            "stage_history": item.stage_history,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        item.advance(MandateStage.COMPLETED, "Pipeline complete")
        self._stats["total_completed"] += 1

        logger.info(
            "[BRL] ✓ %s complete — agent=%s, risk=%d, cost=$%.2f, stages=%d",
            item.id, item.target_agent, item.risk_score,
            item.cost_cents / 100, len(item.stage_history),
        )

    # ── Fleet Health ────────────────────────────────────────────────

    async def _fleet_health_loop(self) -> None:
        """Periodically check DL fleet health."""
        while self._running:
            try:
                if self.dl_bridge:
                    self._last_fleet_status = await self.dl_bridge.fleet_status()
                    logger.debug("[BRL] Fleet health: %s", self._last_fleet_status.get("status"))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[BRL] Fleet health check failed: %s", e)
            await asyncio.sleep(FLEET_HEALTH_INTERVAL)

    # ── Helpers ─────────────────────────────────────────────────────

    def _route_to_agent(self, mandate: dict) -> str:
        """Route mandate to the best DL agent based on content analysis."""
        from ..digital_labour_bridge import MANDATE_TO_AGENT

        title = (mandate.get("title", "") + " " + mandate.get("objective", "")).lower()
        pillar = mandate.get("pillar", "").lower()

        for keyword, agent in MANDATE_TO_AGENT.items():
            if keyword in title or keyword in pillar:
                return agent

        # Fallback routing by pillar
        if pillar in ("brs", "revenue", "sales"):
            return "sales_ops"
        elif pillar in ("aac", "capital", "finance"):
            return "market_research"
        elif pillar in ("ncc", "operations", "ops"):
            return "data_entry"
        return "market_research"

    async def _write_mwp_artifact(self, stage_dir: str, item_id: str, data: dict) -> None:
        """Write an artifact to the MWP workspace stage directory."""
        try:
            target = self._mwp_base / stage_dir / "output"
            target.mkdir(parents=True, exist_ok=True)
            artifact_file = target / f"{item_id}.json"
            artifact_file.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.warning("[BRL] MWP artifact write failed (%s/%s): %s", stage_dir, item_id, e)

    async def _notify(self, title: str, body: str, priority: int = 3) -> None:
        """Send notification via injected notify function."""
        if self.notify_fn:
            try:
                await self.notify_fn(title, body, priority)
            except Exception as e:
                logger.warning("[BRL] Notification failed: %s", e)
