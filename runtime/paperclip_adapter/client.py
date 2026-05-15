"""
NCL Paperclip adapter client — Direct HTTP implementation.

Talks directly to the Paperclip API via httpx. No external nartix_shared
dependency required.

Built against REAL Paperclip API endpoints:
  - POST   /api/companies                       → Create company
  - POST   /api/companies/:id/agents            → Create agent
  - POST   /api/companies/:id/issues            → Create issue (mandate)
  - PATCH  /api/companies/:id/issues/:id        → Update issue
  - POST   /api/companies/:id/cost-events       → Report API cost
  - POST   /api/companies/:id/approvals         → Request approval
  - GET    /api/companies/:id/activity          → Audit log
  - GET    /api/companies/:id/budgets/overview  → Budget overview
  - GET    /api/companies/:id/agents            → List agents
  - GET    /api/companies/:id/issues            → List issues
  - GET    /health                              → Health check
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional, TypeVar

import httpx

log = logging.getLogger("ncl.paperclip_adapter")

_T = TypeVar("_T")
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0


async def _with_retry(
    coro_fn: Callable[[], Coroutine[Any, Any, _T]],
    *,
    attempts: int = _RETRY_ATTEMPTS,
    base_delay: float = _RETRY_BASE_DELAY,
    label: str = "operation",
) -> _T:
    """Call ``coro_fn()`` up to ``attempts`` times with exponential backoff."""
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, attempts + 1):
        try:
            return await coro_fn()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            # Don't retry client errors (4xx)
            if 400 <= exc.response.status_code < 500:
                raise
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                label, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
        except Exception as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                label, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc


class PaperclipClient:
    """
    NCL Paperclip client using direct HTTP calls via httpx.

    No dependency on nartix_shared — talks straight to the Paperclip REST API.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        company_id: Optional[str] = None,
        agent_api_key: Optional[str] = None,
        session_token: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("PAPERCLIP_URL", "http://localhost:3100")).rstrip("/")
        self.company_id = company_id or os.getenv("PAPERCLIP_COMPANY_ID", "")
        self.agent_api_key = agent_api_key or os.getenv("PAPERCLIP_AGENT_KEY", "")
        self.session_token = session_token or os.getenv("PAPERCLIP_SESSION_TOKEN", "")
        self.timeout = timeout

        # Build default headers
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.agent_api_key:
            headers["Authorization"] = f"Bearer {self.agent_api_key}"
        if self.session_token:
            headers["X-Session-Token"] = self.session_token

        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
        )

        # Cache for registrations
        self.agent_ids: dict[str, str] = {}
        self.issue_ids: dict[str, str] = {}  # mandate_id -> issue_id

        log.info(f"NCL Paperclip adapter initialized (url: {self.base_url}, company: {self.company_id})")

    # ── Internal helpers ─────────────────────────────────────────────────

    def _company_url(self, path: str = "") -> str:
        """Build URL under /api/companies/:id/..."""
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first or set PAPERCLIP_COMPANY_ID.")
        return f"/api/companies/{self.company_id}{path}"

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: Optional[dict] = None) -> Any:
        resp = await self._http.post(path, json=json or {})
        resp.raise_for_status()
        return resp.json()

    async def _patch(self, path: str, json: Optional[dict] = None) -> Any:
        resp = await self._http.patch(path, json=json or {})
        resp.raise_for_status()
        return resp.json()

    # ── Company ──────────────────────────────────────────────────────────

    async def register_company(
        self, name: str = "NCL Brain", description: str = "", budget_monthly_cents: int = 100000
    ) -> str:
        """Register NCL as a company in Paperclip. Returns company ID.

        If PAPERCLIP_COMPANY_ID is already set (agent-key auth flow), skip
        the POST /api/companies call (which is admin-only and 403s for
        agent keys). The brain doesn't need to create a company — it just
        needs to know its ID.
        """
        if self.company_id:
            log.info(f"Using pre-configured company_id: {self.company_id}")
            return self.company_id
        try:
            result = await _with_retry(
                lambda: self._post("/api/companies", json={
                    "name": name,
                    "description": description or "NCL - Think, Research, Plan, Decide",
                    "issuePrefix": "NCL",
                    "budgetMonthlyCents": budget_monthly_cents,
                }),
                label="register_company",
            )
            self.company_id = result.get("id", self.company_id)
            log.info(f"Registered company NCL (id: {self.company_id})")
            return self.company_id
        except Exception as e:
            log.error(f"Failed to register company: {e}")
            raise RuntimeError(f"Company registration failed: {e}") from e

    # ── Agents ───────────────────────────────────────────────────────────

    async def register_agent(
        self, name: str, description: str = "", role: str = "general"
    ) -> str:
        """Register a sub-division as an agent. Returns agent ID.

        Idempotent: if an agent with this name already exists in the
        company, return its ID instead of failing.
        """
        try:
            paperclip_role = self._map_role(role)
            result = await _with_retry(
                lambda: self._post(self._company_url("/agents"), json={
                    "name": name,
                    "role": paperclip_role,
                    "adapterType": "claude_local",
                    "adapterConfig": {
                        "name": name,
                        "model": "claude-opus-4-20250514",
                        "description": description,
                    },
                }),
                label=f"register_agent:{name}",
            )
            agent_id = result.get("id", "")
            if agent_id:
                self.agent_ids[name] = agent_id
                log.info(f"Registered agent '{name}' (id: {agent_id})")
            return agent_id
        except Exception as e:
            # Try to look up an existing agent by name (idempotent path)
            try:
                existing = await self.list_agents()
                for a in existing:
                    if a.get("name") == name:
                        agent_id = a.get("id", "")
                        self.agent_ids[name] = agent_id
                        log.info(f"Agent '{name}' already exists (id: {agent_id}) — reusing")
                        return agent_id
            except Exception:
                pass
            # Agent-key auth can't create new agents (admin-only). Don't
            # fail brain startup — log and return empty id so init proceeds.
            log.warning(
                f"Could not register agent '{name}' ({e}); continuing without it. "
                "Create the agent in Paperclip UI if needed."
            )
            return ""

    async def list_agents(self, status: Optional[str] = None) -> list[dict]:
        """List all agents in the company."""
        try:
            params = {}
            if status:
                params["status"] = status
            result = await self._get(self._company_url("/agents"), params=params or None)
            agents = result if isinstance(result, list) else result.get("data", result.get("agents", []))
            log.info(f"Retrieved {len(agents)} agents")
            return agents
        except Exception as e:
            log.error(f"Failed to list agents: {e}")
            raise RuntimeError(f"Agent listing failed: {e}") from e

    # ── Mandates (Issues) ────────────────────────────────────────────────

    async def create_mandate_as_issue(
        self,
        mandate_id: str,
        pillar: str,
        title: str,
        objective: str,
        priority: str = "high",
        assigned_agent_id: Optional[str] = None,
        success_criteria: Optional[list[str]] = None,
        deadline: Optional[str] = None,
    ) -> str:
        """Create a NARTIX mandate as a Paperclip issue. Returns issue ID."""
        try:
            description_parts = [
                f"**Mandate ID**: {mandate_id}",
                f"**Pillar**: {pillar}",
                f"**Objective**: {objective}",
            ]
            if success_criteria:
                description_parts.append("\n**Success Criteria**:")
                for sc in success_criteria:
                    description_parts.append(f"- {sc}")
            if deadline:
                description_parts.append(f"\n**Deadline**: {deadline}")

            body: dict[str, Any] = {
                "title": title,
                "description": "\n".join(description_parts),
                "priority": priority,
                "labels": [pillar],
            }
            if assigned_agent_id:
                body["assignedAgentId"] = assigned_agent_id

            result = await _with_retry(
                lambda: self._post(self._company_url("/issues"), json=body),
                label=f"create_mandate_as_issue:{mandate_id}",
            )
            issue_id = result.get("id", "")
            if issue_id:
                self.issue_ids[mandate_id] = issue_id
                log.info(f"Created mandate issue (mandate_id: {mandate_id}, issue: {result.get('identifier')})")
            return issue_id
        except Exception as e:
            log.error(f"Failed to create mandate issue '{mandate_id}': {e}")
            raise RuntimeError(f"Mandate issue creation failed for '{mandate_id}': {e}") from e

    async def update_mandate_status(
        self, mandate_id: str, status: str, notes: Optional[str] = None
    ) -> None:
        """Update mandate issue status."""
        issue_id = self.issue_ids.get(mandate_id)
        if not issue_id:
            raise RuntimeError(
                f"Mandate '{mandate_id}' not found. "
                f"Create it first via create_mandate_as_issue()."
            )
        try:
            body: dict[str, Any] = {"status": status}
            if notes and status == "closed":
                body["description"] = f"Completed: {notes}"
            await _with_retry(
                lambda: self._patch(self._company_url(f"/issues/{issue_id}"), json=body),
                label=f"update_mandate_status:{mandate_id}",
            )
            log.info(f"Updated mandate '{mandate_id}' to status '{status}'")
        except Exception as e:
            log.error(f"Failed to update mandate '{mandate_id}' status: {e}")
            raise RuntimeError(f"Mandate status update failed for '{mandate_id}': {e}") from e

    async def list_issues(
        self, status: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """List all issues (mandates) in the company."""
        try:
            params: dict[str, Any] = {"limit": limit}
            if status:
                params["status"] = status
            result = await self._get(self._company_url("/issues"), params=params)
            issues = result if isinstance(result, list) else result.get("data", result.get("issues", []))
            log.info(f"Retrieved {len(issues)} issues (status: {status or 'any'})")
            return issues
        except Exception as e:
            log.error(f"Failed to list issues: {e}")
            raise RuntimeError(f"Issue listing failed: {e}") from e

    # ── Cost tracking ────────────────────────────────────────────────────

    async def report_cost(
        self,
        agent_name: str,
        model: str,
        cost_cents: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Report an API cost event. Returns cost event ID."""
        agent_id = self.agent_ids.get(agent_name)
        if not agent_id:
            raise RuntimeError(
                f"Agent '{agent_name}' not found. Register it first via register_agent()."
            )
        try:
            result = await self._post(self._company_url("/cost-events"), json={
                "agentId": agent_id,
                "model": model,
                "costCents": cost_cents,
                "metadata": metadata or {},
            })
            cost_id = result.get("id", "")
            log.info(f"Reported cost for '{agent_name}' on {model}: {cost_cents} cents (event: {cost_id})")
            return cost_id
        except Exception as e:
            log.error(f"Failed to report cost for '{agent_name}': {e}")
            raise RuntimeError(f"Cost reporting failed for '{agent_name}': {e}") from e

    # ── Activity log ─────────────────────────────────────────────────────

    async def log_activity(
        self,
        action: str,
        entity_type: str,
        agent_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log an activity for audit trail (uses 0-cost event as marker)."""
        agent_id = ""
        if agent_name:
            agent_id = self.agent_ids.get(agent_name, "")
            if not agent_id:
                log.warning(f"Agent '{agent_name}' not in cache, logging without agent_id")

        try:
            await self._post(self._company_url("/cost-events"), json={
                "agentId": agent_id,
                "model": "audit",
                "costCents": 0,
                "metadata": {
                    "action": action,
                    "entity_type": entity_type,
                    "details": details or {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
            log.info(f"Logged activity: [{action}] {entity_type} by agent:{agent_name or 'system'}")
        except Exception as e:
            log.error(f"Failed to log activity [{action}]: {e}")
            raise RuntimeError(f"Activity logging failed: {e}") from e

    async def get_activity_log(
        self, agent_name: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """Retrieve activity log."""
        try:
            params: dict[str, Any] = {"limit": limit}
            if agent_name:
                agent_id = self.agent_ids.get(agent_name)
                if agent_id:
                    params["agentId"] = agent_id
            result = await self._get(self._company_url("/activity"), params=params)
            activities = result if isinstance(result, list) else result.get("data", result.get("activities", []))
            log.info(f"Retrieved {len(activities)} activity entries")
            return activities
        except Exception as e:
            log.error(f"Failed to get activity log: {e}")
            raise RuntimeError(f"Activity log retrieval failed: {e}") from e

    # ── Budget ───────────────────────────────────────────────────────────

    async def get_budget_overview(self) -> dict:
        """Get budget status for the company."""
        try:
            result = await self._get(self._company_url("/budgets/overview"))
            log.info(f"Retrieved budget overview for company {self.company_id}")
            return result
        except Exception as e:
            log.error(f"Failed to get budget overview: {e}")
            raise RuntimeError(f"Budget overview retrieval failed: {e}") from e

    # ── Approvals ────────────────────────────────────────────────────────

    async def request_mandate_approval(
        self,
        mandate_id: str,
        approval_type: str = "mandate_execution",
        notes: Optional[str] = None,
    ) -> str:
        """Request board approval for a mandate. Returns approval ID."""
        issue_id = self.issue_ids.get(mandate_id)
        if not issue_id:
            raise RuntimeError(
                f"Mandate '{mandate_id}' not found. "
                f"Create it first via create_mandate_as_issue()."
            )
        try:
            result = await self._post(self._company_url("/approvals"), json={
                "approvalType": approval_type,
                "payload": {
                    "mandate_id": mandate_id,
                    "notes": notes or "",
                },
                "issueIds": [issue_id],
            })
            approval_id = result.get("id", "")
            log.info(f"Requested approval for mandate '{mandate_id}' (approval: {approval_id})")
            return approval_id
        except Exception as e:
            log.error(f"Failed to request approval for mandate '{mandate_id}': {e}")
            raise RuntimeError(f"Approval request failed for mandate '{mandate_id}': {e}") from e

    # ── Health ───────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check if Paperclip server is reachable and healthy."""
        try:
            resp = await self._http.get("/health")
            is_healthy = resp.status_code == 200
            status = "OK" if is_healthy else f"UNHEALTHY ({resp.status_code})"
            log.info(f"Paperclip health check: {status}")
            return is_healthy
        except Exception as e:
            log.error(f"Health check failed: {e}")
            return False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close HTTP client and cleanup."""
        await self._http.aclose()
        log.info("NCL Paperclip client closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _map_role(role: str) -> str:
        """Map NCL-specific roles to Paperclip roles.

        Valid Paperclip roles: ceo, cto, cmo, cfo, engineer, designer,
        pm, qa, devops, researcher, general
        """
        role_map = {
            "research": "researcher",
            "intelligence": "researcher",
            "strategy": "general",
            "memory": "general",
            "executor": "engineer",
            "council_moderator": "ceo",
            "investigate_factcheck": "researcher",
            "youtube_news_trends": "researcher",
            "mobile_intelligence": "pm",
            "execution_support": "engineer",
            "fast_reasoning": "general",
            "scenario_analysis": "researcher",
            "revenue_operations": "cmo",
            "youtube_intelligence": "researcher",
            "x_intelligence": "researcher",
            "intelligence_scanning": "researcher",
        }
        return role_map.get(role, "general")
