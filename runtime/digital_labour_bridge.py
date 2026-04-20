"""BIT RAGE LABOUR Bridge — NCL ↔ BRL Systems integration.
www.bit-rage-labour.com | sales@bit-rage-labour.com

Allows NCL Brain to:
  - Dispatch tasks to the 46-agent BIT RAGE LABOUR fleet
  - Send directives to the BRL Command Dispatcher (agent control, C-Suite, NERVE)
  - Query fleet health and agent status
  - Route mandates to BRL agents when appropriate
  - Read BRL operational data (KPIs, revenue, decisions)

See RESONANCE_ENERGY_SOT.md for system boundaries.

The bridge can operate in two modes:
  1. LOCAL — imports DIGITAL-LABOUR Python modules directly (same Mac)
  2. HTTP  — calls DIGITAL-LABOUR's API endpoints (remote/containerized)

Usage:
    from runtime.digital_labour_bridge import dl_bridge

    # Dispatch a task to the agent fleet
    result = await dl_bridge.dispatch_task("sales_ops", {
        "company_name": "Acme Corp",
        "industry": "SaaS",
        "objective": "cold email sequence"
    })

    # Send BRL directive
    result = await dl_bridge.send_directive("csuite.run", target="boardroom")

    # Get fleet health
    status = await dl_bridge.fleet_status()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger("ncl.digital_labour_bridge")

# ── Configuration ───────────────────────────────────────────────

_DL_BASE = Path(os.getenv("DIGITAL_LABOUR_PATH", str(Path.home() / "dev" / "DIGITAL-LABOUR")))
# Handle nested clone: ~/dev/DIGITAL-LABOUR/DIGITAL-LABOUR/
DL_ROOT = _DL_BASE / "DIGITAL-LABOUR" if (_DL_BASE / "DIGITAL-LABOUR" / "dispatcher").exists() else _DL_BASE
DL_API_URL = os.getenv("DIGITAL_LABOUR_API_URL", "http://localhost:8001")
DL_MODE = os.getenv("DIGITAL_LABOUR_MODE", "local")  # "local" or "http"

# Agent type mapping — maps NCL mandate pillars/types to DL agent types
MANDATE_TO_AGENT = {
    # Revenue / Sales
    "sales": "sales_outreach",
    "outreach": "sales_outreach",
    "lead_generation": "lead_gen",
    "lead": "lead_gen",
    "email_marketing": "email_marketing",
    "cold_email": "sales_outreach",
    "proposal": "proposal_writer",
    # Content
    "content": "content_repurpose",
    "seo": "seo_content",
    "social_media": "social_media",
    "blog": "seo_content",
    "press_release": "press_release",
    "ad_copy": "ad_copy",
    "product": "product_desc",
    "resume": "resume_writer",
    # Technical
    "tech_docs": "tech_docs",
    "documentation": "tech_docs",
    # Business / Research
    "business_plan": "business_plan",
    "market_research": "market_research",
    "research": "market_research",
    "ops_brief": "ops_brief",
    # Operations
    "support": "support_ticket",
    "ticket": "support_ticket",
    "data_entry": "data_entry",
    "bookkeeping": "bookkeeping",
    "crm": "crm_ops",
    "web_scraping": "web_scraper",
    "scrape": "web_scraper",
    "extract": "doc_extract",
    # Freelance platforms
    "freelance": "freelancer_work",
    "upwork": "upwork_work",
    "fiverr": "fiverr_work",
    "pph": "pph_work",
    "guru": "guru_work",
}


class DigitalLabourBridge:
    """Bridge between NCL Brain and DIGITAL-LABOUR fleet."""

    def __init__(self):
        self._local_available: Optional[bool] = None
        self._orchestrator = None
        self._router = None
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def available(self) -> bool:
        """Check if DIGITAL-LABOUR is accessible."""
        if self._local_available is not None:
            return self._local_available
        if DL_MODE == "local":
            self._local_available = DL_ROOT.exists() and (DL_ROOT / "dispatcher" / "command_dispatcher.py").exists()
        else:
            self._local_available = True  # HTTP mode assumes available, will fail on request
        return self._local_available

    def _ensure_local_imports(self):
        """Add DIGITAL-LABOUR to sys.path for local imports."""
        dl_str = str(DL_ROOT)
        if dl_str not in sys.path:
            sys.path.insert(0, dl_str)

    def _get_orchestrator(self):
        """Lazy-load the BRL command dispatcher module."""
        if self._orchestrator is None and DL_MODE == "local":
            self._ensure_local_imports()
            try:
                from dispatcher.command_dispatcher import dispatch, health, pending_decisions
                self._orchestrator = {
                    "dispatch": dispatch,
                    "health": health,
                    "pending_decisions": pending_decisions,
                }
                logger.info("DIGITAL-LABOUR command dispatcher loaded (local mode)")
            except ImportError as e:
                logger.warning("Cannot import DIGITAL-LABOUR command dispatcher: %s", e)
                self._orchestrator = {}
        return self._orchestrator or {}

    def _get_router(self):
        """Lazy-load the task dispatcher/router module."""
        if self._router is None and DL_MODE == "local":
            self._ensure_local_imports()
            try:
                from dispatcher.router import route_task, create_event
                self._router = {
                    "route_task": route_task,
                    "create_event": create_event,
                }
                logger.info("DIGITAL-LABOUR task router loaded (local mode)")
            except ImportError as e:
                logger.warning("Cannot import DIGITAL-LABOUR router: %s", e)
                self._router = {}
        return self._router or {}

    async def _http_client_instance(self) -> httpx.AsyncClient:
        """Get or create HTTP client for remote mode."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=DL_API_URL,
                timeout=30.0,
                headers={"Content-Type": "application/json"},
            )
        return self._http_client

    # ── BRL Directives ──────────────────────────────────────────

    async def send_directive(
        self, directive_type: str, target: str = "", data: dict = None, reason: str = ""
    ) -> dict:
        """Send a directive to the BRL Command Dispatcher.

        Supported types: agent.pause, agent.resume, csuite.run, csuite.quick,
                         nerve.restart, nerve.stop, resonance.sync,
                         outreach.push, outreach.followups, system.check, relay.publish
        """
        directive = {
            "type": directive_type,
            "target": target,
            "data": data or {},
            "reason": reason,
            "operator": "NCL-Brain",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if DL_MODE == "local":
            orch = self._get_orchestrator()
            if "dispatch" not in orch:
                return {"executed": False, "error": "BRL command dispatcher not available locally"}
            # Run sync function in thread to avoid blocking
            result = await asyncio.to_thread(orch["dispatch"], directive)
            return result
        else:
            client = await self._http_client_instance()
            try:
                resp = await client.post("/admin/directive", json=directive)
                return resp.json()
            except Exception as e:
                return {"executed": False, "error": str(e)}

    # ── Task Dispatch ───────────────────────────────────────────

    async def dispatch_task(
        self, agent_type: str, task_data: dict, priority: int = 5
    ) -> dict:
        """Dispatch a task to a specific DL agent.

        Args:
            agent_type: The agent to run (e.g., "sales_ops", "market_research")
            task_data: Agent-specific input data
            priority: 1-10 priority level
        """
        task = {
            "agent_type": agent_type,
            "input": task_data,
            "priority": priority,
            "source": "ncl-brain",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if DL_MODE == "local":
            router = self._get_router()
            if "route_task" not in router:
                return {"status": "error", "error": "Task router not available locally"}
            try:
                result = await asyncio.to_thread(router["route_task"], task)
                return {"status": "dispatched", "result": result}
            except Exception as e:
                return {"status": "error", "error": str(e)}
        else:
            client = await self._http_client_instance()
            try:
                resp = await client.post("/tasks", json=task)
                return resp.json()
            except Exception as e:
                return {"status": "error", "error": str(e)}

    # ── Mandate → DL Task Routing ───────────────────────────────

    async def route_mandate_to_agent(self, mandate: dict) -> dict:
        """Intelligently route an NCL mandate to the appropriate DL agent.

        Analyzes the mandate title, objective, and pillar to determine
        which DL agent should handle it.
        """
        title = (mandate.get("title", "") + " " + mandate.get("objective", "")).lower()
        pillar = mandate.get("pillar", "").lower()

        # Find best matching agent
        best_agent = None
        for keyword, agent in MANDATE_TO_AGENT.items():
            if keyword in title or keyword in pillar:
                best_agent = agent
                break

        if not best_agent:
            # Default: market_research for intelligence, sales_outreach for revenue
            if pillar in ("brs", "revenue", "sales"):
                best_agent = "sales_outreach"
            elif pillar in ("aac", "capital", "finance"):
                best_agent = "market_research"
            else:
                best_agent = "market_research"

        task_data = {
            "mandate_id": mandate.get("mandate_id", ""),
            "title": mandate.get("title", ""),
            "objective": mandate.get("objective", ""),
            "success_criteria": mandate.get("success_criteria", []),
            "context": mandate.get("context", {}),
            "source": "ncl-mandate",
        }

        return await self.dispatch_task(best_agent, task_data, priority=mandate.get("priority", 5))

    # ── Fleet Status ────────────────────────────────────────────

    async def fleet_status(self) -> dict:
        """Get DIGITAL-LABOUR fleet health and status."""
        if DL_MODE == "local":
            orch = self._get_orchestrator()
            if "health" not in orch:
                return {"status": "unavailable", "mode": "local", "dl_root": str(DL_ROOT)}

            health = await asyncio.to_thread(orch["health"])

            # Read additional status files
            status = {
                "status": "online",
                "mode": "local",
                "dl_root": str(DL_ROOT),
                "orchestrator": health,
                "agents": {},
                "nerve": {},
                "revenue": {},
            }

            # Check NERVE status
            stop_flag = DL_ROOT / "data" / "watchdog_stop.flag"
            status["nerve"]["running"] = not stop_flag.exists()

            # Check paused agents
            pause_file = DL_ROOT / "data" / "paused_agents.json"
            if pause_file.exists():
                try:
                    paused = json.loads(pause_file.read_text("utf-8"))
                    status["agents"]["paused"] = paused
                except Exception:
                    status["agents"]["paused"] = []
            else:
                status["agents"]["paused"] = []

            # Count total agents from registry
            registry_file = DL_ROOT / "config" / "agent_registry.json"
            if registry_file.exists():
                try:
                    reg = json.loads(registry_file.read_text("utf-8"))
                    agents = reg.get("agents", {})
                    status["agents"]["total"] = len(agents)
                    status["agents"]["active"] = len(agents) - len(status["agents"]["paused"])
                except Exception:
                    status["agents"]["total"] = 30
                    status["agents"]["active"] = 30

            # Read recent KPIs
            kpi_file = DL_ROOT / "kpi" / "kpi_log.jsonl"
            if kpi_file.exists():
                try:
                    lines = kpi_file.read_text("utf-8").strip().splitlines()
                    recent = [json.loads(l) for l in lines[-10:] if l.strip()]
                    status["recent_kpis"] = recent
                except Exception:
                    status["recent_kpis"] = []

            # Read recent BRL command decisions
            if "pending_decisions" in orch:
                try:
                    decisions = await asyncio.to_thread(orch["pending_decisions"], 5)
                    status["recent_decisions"] = decisions
                except Exception:
                    status["recent_decisions"] = []

            return status
        else:
            client = await self._http_client_instance()
            try:
                resp = await client.get("/health")
                return resp.json()
            except Exception as e:
                return {"status": "unreachable", "error": str(e)}

    # ── C-Suite ─────────────────────────────────────────────────

    async def run_csuite_meeting(self, quick: bool = False) -> dict:
        """Trigger a C-Suite board meeting (AXIOM + VECTIS + LEDGR)."""
        dtype = "csuite.quick" if quick else "csuite.run"
        return await self.send_directive(dtype, target="boardroom")

    async def run_executive(self, executive: str) -> dict:
        """Run a specific C-Suite executive (axiom/vectis/ledgr)."""
        return await self.send_directive("csuite.run", target=executive)

    # ── NERVE Control ───────────────────────────────────────────

    async def nerve_start(self) -> dict:
        """Start/restart the NERVE autonomous daemon."""
        return await self.send_directive("nerve.restart")

    async def nerve_stop(self) -> dict:
        """Stop the NERVE autonomous daemon."""
        return await self.send_directive("nerve.stop")

    # ── Agent Control ───────────────────────────────────────────

    async def pause_agent(self, agent_name: str, reason: str = "") -> dict:
        """Pause a specific agent."""
        return await self.send_directive("agent.pause", target=agent_name, reason=reason)

    async def resume_agent(self, agent_name: str) -> dict:
        """Resume a paused agent."""
        return await self.send_directive("agent.resume", target=agent_name)

    # ── Cross-Pillar Sync ───────────────────────────────────────

    async def trigger_sync(self) -> dict:
        """Trigger cross-pillar resonance sync (NCL ↔ DL ↔ AAC)."""
        return await self.send_directive("resonance.sync")

    # ── Outreach ────────────────────────────────────────────────

    async def push_outreach(self) -> dict:
        """Trigger email outreach push (50 emails)."""
        return await self.send_directive("outreach.push")

    async def run_followups(self) -> dict:
        """Run automated follow-up sequences."""
        return await self.send_directive("outreach.followups")

    # ── System Diagnostics ──────────────────────────────────────

    async def system_check(self) -> dict:
        """Run full system diagnostic on DIGITAL-LABOUR."""
        return await self.send_directive("system.check")

    # ── Cleanup ─────────────────────────────────────────────────

    async def close(self):
        """Close HTTP client if open."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# Module-level singleton
dl_bridge = DigitalLabourBridge()
