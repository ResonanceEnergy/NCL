"""
NCL Paperclip adapter client.

Wraps the universal PaperclipClient from nartix-shared and provides
NCL-specific convenience methods for mandate registration, cost tracking,
and activity logging.

Built against REAL Paperclip API endpoints:
  - POST   /api/companies                       → Create company
  - POST   /api/companies/:id/agents            → Create agent
  - POST   /api/companies/:id/issues            → Create issue (mandate)
  - PATCH  /api/companies/:id/issues/:id        → Update issue
  - POST   /api/companies/:id/cost-events       → Report API cost
  - POST   /api/companies/:id/approvals         → Request approval
  - GET    /api/companies/:id/activity          → Audit log
  - GET    /api/companies/:id/budgets/overview  → Budget overview
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("ncl.paperclip_adapter")


class PaperclipClient:
    """
    NCL-specific Paperclip client with mandate lifecycle and cost tracking.

    This client wraps the universal PaperclipClient from nartix-shared
    and adds NCL-specific business logic for mandate registration,
    activity logging, and cost reporting.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        company_id: Optional[str] = None,
        agent_api_key: Optional[str] = None,
        session_token: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        """
        Initialize NCL Paperclip client.

        Args:
            base_url: Paperclip server URL (e.g., http://localhost:3100)
                     Defaults to PAPERCLIP_URL env var or http://localhost:3100
            company_id: Company UUID (loaded from cache or created on first use)
                       Defaults to PAPERCLIP_COMPANY_ID env var
            agent_api_key: Agent API key in format "publicKey:secretKey"
                          Defaults to PAPERCLIP_AGENT_KEY env var
            session_token: Board session token for admin operations
                          Defaults to PAPERCLIP_SESSION_TOKEN env var
            timeout: HTTP timeout in seconds (default: 15)
        """
        # Import the universal client here to avoid hard dependency
        try:
            from nartix_shared.paperclip.client import PaperclipClient as UniversalClient
            self._universal_client_class = UniversalClient
        except ImportError:
            log.warning(
                "Could not import universal PaperclipClient from nartix-shared. "
                "Will use local implementation."
            )
            self._universal_client_class = None

        self.base_url = base_url or os.getenv("PAPERCLIP_URL", "http://localhost:3100")
        self.company_id = company_id or os.getenv("PAPERCLIP_COMPANY_ID", "")
        self.agent_api_key = agent_api_key or os.getenv("PAPERCLIP_AGENT_KEY", "")
        self.session_token = session_token or os.getenv("PAPERCLIP_SESSION_TOKEN", "")
        self.timeout = timeout

        # Initialize the wrapped universal client
        if self._universal_client_class:
            self._client = self._universal_client_class(
                base_url=self.base_url,
                company_id=self.company_id,
                agent_api_key=self.agent_api_key,
                session_token=self.session_token,
                timeout=timeout,
            )
        else:
            self._client = None

        # Cache for NCL-specific registrations
        self.agent_ids: dict[str, str] = {}
        self.issue_ids: dict[str, str] = {}  # mandate_id -> issue_id

        log.info(f"NCL Paperclip adapter initialized (url: {self.base_url})")

    async def register_company(
        self, name: str = "NCL Brain", description: str = "", budget_monthly_cents: int = 100000
    ) -> str:
        """
        Register NCL as a company in Paperclip.

        Args:
            name: Company name (default: "NCL Brain")
            description: Company description
            budget_monthly_cents: Monthly budget in cents (default: $1000)

        Returns:
            Company ID (stored in self.company_id for future operations)

        Raises:
            RuntimeError: If Paperclip is unavailable or API fails
        """
        if not self._client:
            raise RuntimeError(
                "Universal Paperclip client not available. "
                "Ensure nartix-shared is installed."
            )

        try:
            result = await self._client.create_company(
                name=name,
                description=description or "NCL - Think, Research, Plan, Decide",
                issue_prefix="NCL",
                budget_monthly_cents=budget_monthly_cents,
            )
            self.company_id = result.get("id", self.company_id)
            log.info(f"Registered company NCL (id: {self.company_id})")
            return self.company_id
        except Exception as e:
            log.error(f"Failed to register company: {e}")
            raise RuntimeError(f"Company registration failed: {e}") from e

    async def register_agent(
        self, name: str, description: str, role: str = "general"
    ) -> str:
        """
        Register a sub-division as an agent in Paperclip.

        Args:
            name: Agent name (e.g., "UNI Research", "Awarebot-FPC")
            description: Agent description
            role: Agent role ("general", "specialist", "ceo")

        Returns:
            Agent ID (cached in self.agent_ids[name])

        Raises:
            RuntimeError: If company not registered or API fails
        """
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first.")

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            # Map NCL-specific roles to Paperclip roles
            paperclip_role = self._map_role(role)

            result = await self._client.create_agent(
                name=name,
                role=paperclip_role,
                adapter_type="claude_local",
                adapter_config={
                    "name": name,
                    "model": "claude-opus-4-6",
                },
            )
            agent_id = result.get("id", "")
            if agent_id:
                self.agent_ids[name] = agent_id
                log.info(f"Registered agent '{name}' (id: {agent_id})")
            return agent_id
        except Exception as e:
            log.error(f"Failed to register agent '{name}': {e}")
            raise RuntimeError(f"Agent registration failed for '{name}': {e}") from e

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
        """
        Create a NARTIX mandate as a Paperclip issue.

        Maps mandate fields to issue fields:
          mandate_id → description
          pillar → label
          priority → priority
          success_criteria → description bullets

        Args:
            mandate_id: NCL mandate ID (e.g., "MANDATE-001")
            pillar: Target pillar (NCC, BRS, AAC)
            title: Mandate title
            objective: Strategic objective
            priority: Priority level ("low", "medium", "high", "critical")
            assigned_agent_id: Agent UUID to assign
            success_criteria: List of success criteria
            deadline: Optional deadline (ISO 8601 format)

        Returns:
            Issue ID (cached in self.issue_ids[mandate_id])

        Raises:
            RuntimeError: If company not registered or API fails
        """
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first.")

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            # Build description with mandate metadata
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

            result = await self._client.create_mandate_as_issue(
                mandate_id=mandate_id,
                pillar=pillar,
                title=title,
                objective=objective,
                priority=priority,
                assigned_agent_id=assigned_agent_id,
                success_criteria=success_criteria,
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
        """
        Update mandate issue status.

        Args:
            mandate_id: Mandate ID (must have been created via create_mandate_as_issue)
            status: New status ("open", "in_progress", "closed")
            notes: Optional completion notes

        Raises:
            RuntimeError: If mandate not found or API fails
        """
        issue_id = self.issue_ids.get(mandate_id)
        if not issue_id:
            raise RuntimeError(
                f"Mandate '{mandate_id}' not found. "
                f"Create it first via create_mandate_as_issue()."
            )

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            await self._client.update_issue(
                issue_id=issue_id,
                status=status,
                description=f"Completed: {notes}" if notes and status == "closed" else None,
            )
            log.info(f"Updated mandate '{mandate_id}' to status '{status}'")
        except Exception as e:
            log.error(f"Failed to update mandate '{mandate_id}' status: {e}")
            raise RuntimeError(f"Mandate status update failed for '{mandate_id}': {e}") from e

    async def report_cost(
        self,
        agent_name: str,
        model: str,
        cost_cents: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Report an API cost event for an agent.

        Args:
            agent_name: Agent name (must have been registered via register_agent)
            model: Model name (e.g., "claude-sonnet-4-6", "grok-3")
            cost_cents: Cost in cents
            metadata: Optional metadata

        Returns:
            Cost event ID

        Raises:
            RuntimeError: If agent not found or API fails
        """
        agent_id = self.agent_ids.get(agent_name)
        if not agent_id:
            raise RuntimeError(
                f"Agent '{agent_name}' not found. Register it first via register_agent()."
            )

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            result = await self._client.report_cost(
                agent_id=agent_id,
                model=model,
                cost_cents=cost_cents,
                metadata=metadata,
            )
            cost_id = result.get("id", "")
            log.info(
                f"Reported cost for '{agent_name}' on {model}: {cost_cents} cents "
                f"(event: {cost_id})"
            )
            return cost_id
        except Exception as e:
            log.error(f"Failed to report cost for '{agent_name}': {e}")
            raise RuntimeError(f"Cost reporting failed for '{agent_name}': {e}") from e

    async def log_activity(
        self,
        action: str,
        entity_type: str,
        agent_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Log an activity for audit trail.

        This is a convenience method that leverages Paperclip's auto-logging
        of issue and agent operations. For custom events, we create cost events
        with 0 cost as markers.

        Args:
            action: Action performed (e.g., "mandate_created", "council_spawned")
            entity_type: Entity type (e.g., "mandate", "council", "feedback")
            agent_name: Agent that performed the action
            details: Additional metadata

        Raises:
            RuntimeError: If agent not found (if agent_name provided)
        """
        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        agent_id = None
        if agent_name:
            agent_id = self.agent_ids.get(agent_name)
            if not agent_id:
                raise RuntimeError(
                    f"Agent '{agent_name}' not found. Register it first via register_agent()."
                )

        try:
            # Use cost event with 0 cost as audit marker
            await self._client.report_cost(
                agent_id=agent_id or "",
                model="audit",
                cost_cents=0,
                metadata={
                    "action": action,
                    "entity_type": entity_type,
                    "details": details or {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            log.info(
                f"Logged activity: [{action}] {entity_type} "
                f"by agent:{agent_name or 'system'}"
            )
        except Exception as e:
            log.error(f"Failed to log activity [{action}]: {e}")
            raise RuntimeError(f"Activity logging failed: {e}") from e

    async def get_budget_overview(self) -> dict:
        """
        Get budget status for the company.

        Returns:
            Dict with company and per-agent budget breakdown

        Raises:
            RuntimeError: If company not registered or API fails
        """
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first.")

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            result = await self._client.get_budget_overview()
            log.info(f"Retrieved budget overview for company {self.company_id}")
            return result
        except Exception as e:
            log.error(f"Failed to get budget overview: {e}")
            raise RuntimeError(f"Budget overview retrieval failed: {e}") from e

    async def list_agents(self, status: Optional[str] = None) -> list[dict]:
        """
        List all agents in the company.

        Args:
            status: Optional status filter ("active", "inactive", etc.)

        Returns:
            List of agent dicts

        Raises:
            RuntimeError: If company not registered or API fails
        """
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first.")

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            agents = await self._client.list_agents(status=status)
            log.info(f"Retrieved {len(agents)} agents")
            return agents
        except Exception as e:
            log.error(f"Failed to list agents: {e}")
            raise RuntimeError(f"Agent listing failed: {e}") from e

    async def list_issues(
        self, status: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """
        List all issues (mandates) in the company.

        Args:
            status: Optional status filter ("open", "in_progress", "closed")
            limit: Max results (default: 50)

        Returns:
            List of issue dicts

        Raises:
            RuntimeError: If company not registered or API fails
        """
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first.")

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            issues = await self._client.list_issues(status=status, limit=limit)
            log.info(f"Retrieved {len(issues)} issues (status: {status or 'any'})")
            return issues
        except Exception as e:
            log.error(f"Failed to list issues: {e}")
            raise RuntimeError(f"Issue listing failed: {e}") from e

    async def get_activity_log(
        self, agent_name: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """
        Retrieve activity log (audit trail).

        Args:
            agent_name: Filter by agent (optional)
            limit: Max results (default: 50)

        Returns:
            List of activity dicts

        Raises:
            RuntimeError: If company not registered or API fails
        """
        if not self.company_id:
            raise RuntimeError("Company not registered. Call register_company() first.")

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        agent_id = None
        if agent_name:
            agent_id = self.agent_ids.get(agent_name)

        try:
            activities = await self._client.get_activity_log(agent_id=agent_id, limit=limit)
            log.info(f"Retrieved {len(activities)} activity entries")
            return activities
        except Exception as e:
            log.error(f"Failed to get activity log: {e}")
            raise RuntimeError(f"Activity log retrieval failed: {e}") from e

    async def request_mandate_approval(
        self,
        mandate_id: str,
        approval_type: str = "mandate_execution",
        notes: Optional[str] = None,
    ) -> str:
        """
        Request board approval for a mandate.

        Args:
            mandate_id: Mandate ID
            approval_type: Type of approval (default: "mandate_execution")
            notes: Optional notes for the approval request

        Returns:
            Approval request ID

        Raises:
            RuntimeError: If mandate not found or API fails
        """
        issue_id = self.issue_ids.get(mandate_id)
        if not issue_id:
            raise RuntimeError(
                f"Mandate '{mandate_id}' not found. "
                f"Create it first via create_mandate_as_issue()."
            )

        if not self._client:
            raise RuntimeError("Universal Paperclip client not available.")

        try:
            result = await self._client.request_approval(
                approval_type=approval_type,
                payload={
                    "mandate_id": mandate_id,
                    "notes": notes or "",
                },
                requested_by_agent_id="",  # Will use authenticated agent
                issue_ids=[issue_id],
            )
            approval_id = result.get("id", "")
            log.info(
                f"Requested approval for mandate '{mandate_id}' "
                f"(approval: {approval_id})"
            )
            return approval_id
        except Exception as e:
            log.error(f"Failed to request approval for mandate '{mandate_id}': {e}")
            raise RuntimeError(
                f"Approval request failed for mandate '{mandate_id}': {e}"
            ) from e

    async def health_check(self) -> bool:
        """
        Check if Paperclip server is reachable and healthy.

        Returns:
            True if healthy, False otherwise
        """
        if not self._client:
            log.warning("Universal client not available, health check skipped")
            return False

        try:
            is_healthy = await self._client.health_check()
            status = "OK" if is_healthy else "UNHEALTHY"
            log.info(f"Paperclip health check: {status}")
            return is_healthy
        except Exception as e:
            log.error(f"Health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close HTTP client and cleanup."""
        if self._client:
            await self._client.close()
            log.info("NCL Paperclip client closed")

    @staticmethod
    def _map_role(role: str) -> str:
        """
        Map NCL-specific roles to Paperclip roles.

        Args:
            role: NCL role string

        Returns:
            Paperclip role string
        """
        role_map = {
            "research": "specialist",
            "intelligence": "specialist",
            "strategy": "general",
            "memory": "general",
            "executor": "general",
        }
        return role_map.get(role, role)
