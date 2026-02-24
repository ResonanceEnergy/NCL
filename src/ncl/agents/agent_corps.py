# src/ncl/agents/agent_corps.py
"""
Agent Corps
Specialized agents for each doctrine domain
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from .base_agent import BaseAgent
from .domain_agent import DomainAgent
from .enums import AgentDomain, AgentStatus as AgentStatusEnum, TaskPriority, TaskStatus
from ..core.decision_engine import DecisionEngine
from ..security.faraday_fortress import FaradayFortress


@dataclass
class AgentStatus:
    """Status of an individual agent"""
    agent_id: str
    domain: AgentDomain
    status: AgentStatusEnum = AgentStatusEnum.IDLE
    last_active: Optional[datetime] = None
    tasks_completed: int = 0
    performance_score: float = 100.0
    specialization: List[str] = field(default_factory=list)


@dataclass
class AgentTask:
    """Represents a task assigned to an agent"""
    id: str
    agent_id: str
    domain: AgentDomain
    description: str
    priority: TaskPriority
    created_at: datetime = field(default_factory=datetime.now)
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None


class AgentCorps:
    """
    Agent Corps - Specialized AI agents for doctrine domains

    Implements the Agent Corps Super-Pump from Master Doctrine v2.0,
    providing specialized agents for each domain of operation.
    """

    def __init__(self, decision_engine: DecisionEngine, security: FaradayFortress):
    """__init__ function/class."""

        self.logger = logging.getLogger(__name__)
        self.decision_engine = decision_engine
        self.security = security

        # Agent management
        self.agents: Dict[str, BaseAgent] = {}
        self.agent_status: Dict[str, AgentStatus] = {}
        self.task_queue: List[AgentTask] = []
        self.completed_tasks: List[AgentTask] = []

        # Domain configuration
        self.domain_ranges = {
            AgentDomain.IT_INFRASTRUCTURE: (21, 45),
            AgentDomain.LEGAL_COMPLIANCE: (46, 70),
            AgentDomain.HEALTH_WELLNESS: (71, 95),
            AgentDomain.INTEL_ANALYSIS: (96, 120),
            AgentDomain.PLANNING_STRATEGY: (121, 145),
            AgentDomain.NETWORK_ENGINEERING: (146, 170),
            AgentDomain.AI_RESEARCH: (171, 195),
            AgentDomain.FINANCIAL_OPTIMIZATION: (196, 220),
            AgentDomain.RELATIONSHIP_MANAGEMENT: (221, 245),
            AgentDomain.TIME_ALLOCATION: (246, 270),
            AgentDomain.KNOWLEDGE_DEVELOPMENT: (271, 295),
            AgentDomain.HIRING_RECRUITMENT: (296, 320),
            AgentDomain.TRAINING_DEVELOPMENT: (321, 345),
            AgentDomain.SOP_DOCUMENTATION: (346, 370),
            AgentDomain.AUTOMATION_TOOLS: (371, 395),
            AgentDomain.CEO_GOVERNANCE: (396, 420),
            AgentDomain.FATHERHOOD_FAMILY: (421, 445)
        }

        # Agent capacity management
        self.max_concurrent_tasks = 10
        self.active_tasks = 0

    async def initialize(self) -> bool:
        """Initialize the Agent Corps"""
        try:
            self.logger.info("🤖 Initializing Agent Corps...")

            # Initialize domain agents
            await self._initialize_domain_agents()

            # Start task processing
            asyncio.create_task(self._continuous_task_processing())

            # Start agent health monitoring
            asyncio.create_task(self._continuous_agent_monitoring())

            self.logger.info(f"✅ Agent Corps initialized with {len(self.agents)} agents")
            return True

        except Exception as e:
            self.logger.error(f"❌ Agent Corps initialization failed: {e}")
            return False

    async def _initialize_domain_agents(self):
        """Initialize agents for each doctrine domain"""
        for domain in AgentDomain:
            agent_count = self._calculate_agent_count(domain)

            for i in range(agent_count):
                agent_id = f"{domain.value}_{i+1:02d}"
                agent = self._create_domain_agent(domain, agent_id)
                self.agents[agent_id] = agent

                # Initialize agent status
                self.agent_status[agent_id] = AgentStatus(
                    agent_id=agent_id,
                    domain=domain,
                    specialization=self._get_domain_specializations(domain)
                )

                await agent.initialize()

    def _calculate_agent_count(self, domain: AgentDomain) -> int:
        """Calculate number of agents needed for a domain"""
        min_range, max_range = self.domain_ranges[domain]

        # Base calculation: 1 agent per 5 units of range
        range_size = max_range - min_range + 1
        agent_count = max(1, range_size // 5)

        # Special cases
        if domain == AgentDomain.CEO_GOVERNANCE:
            agent_count = 3  # Multiple CEO support agents
        elif domain == AgentDomain.FATHERHOOD_FAMILY:
            agent_count = 2  # Family and fatherhood specialists

        return agent_count

    def _create_domain_agent(self, domain: AgentDomain, agent_id: str) -> BaseAgent:
        """Create an agent for a specific domain"""
        # Create concrete domain agent
        return DomainAgent(
            agent_id=agent_id,
            domain=domain,
            capabilities=self._get_domain_capabilities(domain)
        )

    def _get_domain_capabilities(self, domain: AgentDomain) -> List[str]:
        """Get capabilities for a domain"""
        capabilities_map = {
            AgentDomain.IT_INFRASTRUCTURE: [
                "system_monitoring", "network_configuration", "security_hardening",
                "backup_management", "performance_optimization"
            ],
            AgentDomain.LEGAL_COMPLIANCE: [
                "contract_review", "regulatory_compliance", "risk_assessment",
                "policy_development", "legal_research"
            ],
            AgentDomain.HEALTH_WELLNESS: [
                "health_monitoring", "wellness_tracking", "ergonomics_assessment",
                "stress_management", "fitness_optimization"
            ],
            AgentDomain.INTEL_ANALYSIS: [
                "threat_detection", "pattern_analysis", "intelligence_gathering",
                "risk_forecasting", "security_intelligence"
            ],
            AgentDomain.PLANNING_STRATEGY: [
                "strategic_planning", "goal_setting", "resource_allocation",
                "performance_tracking", "decision_support"
            ],
            AgentDomain.HIRING_RECRUITMENT: [
                "candidate_sourcing", "interview_coordination", "skill_assessment",
                "cultural_fit_analysis", "onboarding_support"
            ],
            AgentDomain.TRAINING_DEVELOPMENT: [
                "skill_gap_analysis", "training_program_design", "progress_tracking",
                "competency_development", "career_planning"
            ],
            AgentDomain.SOP_DOCUMENTATION: [
                "process_documentation", "standard_operating_procedures", "workflow_optimization",
                "quality_assurance", "knowledge_management"
            ],
            AgentDomain.AUTOMATION_TOOLS: [
                "workflow_automation", "script_development", "integration_setup",
                "api_development", "tool_configuration"
            ],
            AgentDomain.CEO_GOVERNANCE: [
                "executive_decision_support", "strategic_oversight", "board_reporting",
                "crisis_management", "leadership_guidance"
            ],
            AgentDomain.FATHERHOOD_FAMILY: [
                "family_time_optimization", "parenting_support", "work_life_balance",
                "relationship_nurturing", "family_goal_setting"
            ]
        }

        return capabilities_map.get(domain, [])

    def _get_domain_specializations(self, domain: AgentDomain) -> List[str]:
        """Get specializations for a domain"""
        specializations_map = {
            AgentDomain.IT_INFRASTRUCTURE: ["DevOps", "Security", "Networking", "Cloud"],
            AgentDomain.LEGAL_COMPLIANCE: ["Corporate Law", "Data Privacy", "Contracts", "Risk"],
            AgentDomain.HEALTH_WELLNESS: ["Fitness", "Nutrition", "Mental Health", "Ergonomics"],
            AgentDomain.INTEL_ANALYSIS: ["Cybersecurity", "Market Intelligence", "Risk Analysis"],
            AgentDomain.PLANNING_STRATEGY: ["Strategic Planning", "Project Management", "OKRs"],
            AgentDomain.HIRING_RECRUITMENT: ["Talent Acquisition", "HR Tech", "Diversity"],
            AgentDomain.TRAINING_DEVELOPMENT: ["Learning Management", "Skill Development", "Coaching"],
            AgentDomain.SOP_DOCUMENTATION: ["Process Engineering", "Quality Management", "Documentation"],
            AgentDomain.AUTOMATION_TOOLS: ["API Development", "Workflow Automation", "Integration"],
            AgentDomain.CEO_GOVERNANCE: ["Executive Leadership", "Board Governance", "Crisis Management"],
            AgentDomain.FATHERHOOD_FAMILY: ["Parenting", "Family Dynamics", "Work-Life Balance"]
        }

        return specializations_map.get(domain, [])

    async def gather_intelligence(self) -> List[Dict[str, Any]]:
        """Gather intelligence from all active agents"""
        intelligence = []

        for agent in self.agents.values():
            try:
                agent_insights = await agent.gather_intelligence()
                intelligence.extend(agent_insights)
            except Exception as e:
                self.logger.error(f"Error gathering intelligence from {agent.agent_id}: {e}")

        return intelligence

    async def apply_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a decision through appropriate agents"""
        decision_type = decision.get('type')
        affected_components = decision.get('affected_components', [])

        # Find relevant agents
        relevant_agents = self._find_relevant_agents(affected_components)

        results = []
        for agent in relevant_agents:
            try:
                result = await agent.execute_decision(decision)
                results.append(result)
            except Exception as e:
                self.logger.error(f"Error applying decision to {agent.agent_id}: {e}")

        return {
            'decision_applied': decision.get('id', 'unknown'),
            'agents_executed': len(results),
            'results': results
        }

    def _find_relevant_agents(self, components: List[str]) -> List[BaseAgent]:
        """Find agents relevant to specific components"""
        relevant_agents = []

        # Map components to domains
        component_domain_map = {
            'HHP': AgentDomain.HEALTH_WELLNESS,
            'FAO': AgentDomain.PLANNING_STRATEGY,
            'TAA': AgentDomain.AUTOMATION_TOOLS,
            'KDD': AgentDomain.INTEL_ANALYSIS,
            'RNN': AgentDomain.FATHERHOOD_FAMILY,
            'AIN': AgentDomain.IT_INFRASTRUCTURE,
            'NPE': AgentDomain.IT_INFRASTRUCTURE
        }

        for component in components:
            domain = component_domain_map.get(component)
            if domain:
                # Find agents in this domain
                domain_agents = [
                    agent for agent in self.agents.values()
                    if self.agent_status[agent.agent_id].domain == domain
                ]
                relevant_agents.extend(domain_agents[:2])  # Limit to 2 agents per domain

        # If no specific agents found, use general purpose agents
        if not relevant_agents:
            relevant_agents = list(self.agents.values())[:3]

        return relevant_agents

    async def assign_task(self, domain: AgentDomain, description: str, priority: int = 1) -> str:
        """Assign a task to an appropriate agent"""
        # Find available agent in domain
        available_agents = [
            agent_id for agent_id, status in self.agent_status.items()
            if status.domain == domain and status.status == AgentStatusEnum.IDLE
        ]

        if not available_agents:
            # Queue the task
            task = AgentTask(
                id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                agent_id="",  # Will be assigned when agent becomes available
                domain=domain,
                description=description,
                priority=priority
            )
            self.task_queue.append(task)
            return task.id

        # Assign to first available agent
        agent_id = available_agents[0]
        task = AgentTask(
            id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            agent_id=agent_id,
            domain=domain,
            description=description,
            priority=priority,
            assigned_at=datetime.now()
        )

        # Update agent status
        self.agent_status[agent_id].status = AgentStatusEnum.PROCESSING
        self.agent_status[agent_id].last_active = datetime.now()

        # Execute task
        asyncio.create_task(self._execute_task(task))

        return task.id

    async def _execute_task(self, task: AgentTask):
        """Execute a task using the assigned agent"""
        try:
            agent = self.agents[task.agent_id]
            self.active_tasks += 1

            # Execute the task
            result = await agent.execute_task(task.description)

            # Update task
            task.completed_at = datetime.now()
            task.status = TaskStatus.COMPLETED
            task.result = result

            # Update agent status
            self.agent_status[task.agent_id].status = AgentStatusEnum.IDLE
            self.agent_status[task.agent_id].tasks_completed += 1
            self.agent_status[task.agent_id].last_active = datetime.now()

            # Store completed task
            self.completed_tasks.append(task)

        except Exception as e:
            self.logger.error(f"Task execution failed for {task.agent_id}: {e}")
            task.status = TaskStatus.FAILED
            task.result = str(e)
        finally:
            self.active_tasks -= 1

    async def _continuous_task_processing(self):
        """Process queued tasks continuously"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                # Process queued tasks
                if self.task_queue and self.active_tasks < self.max_concurrent_tasks:
                    # Sort by priority (higher number = higher priority)
                    self.task_queue.sort(key=lambda t: t.priority, reverse=True)

                    # Assign highest priority task
                    task = self.task_queue.pop(0)
                    available_agents = [
                        agent_id for agent_id, status in self.agent_status.items()
                        if status.domain == task.domain and status.status == AgentStatusEnum.IDLE
                    ]

                    if available_agents:
                        task.agent_id = available_agents[0]
                        task.assigned_at = datetime.now()
                        self.agent_status[task.agent_id].status = AgentStatusEnum.PROCESSING

                        asyncio.create_task(self._execute_task(task))

            except Exception as e:
                self.logger.error(f"Task processing error: {e}")

    async def _continuous_agent_monitoring(self):
        """Monitor agent health and performance"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes

                for agent_id, status in self.agent_status.items():
                    # Check if agent has been idle too long
                    if status.status == AgentStatusEnum.IDLE and status.last_active:
                        idle_time = datetime.now() - status.last_active
                        if idle_time > timedelta(hours=1):
                            # Perform health check
                            await self._perform_agent_health_check(agent_id)

            except Exception as e:
                self.logger.error(f"Agent monitoring error: {e}")

    async def _perform_agent_health_check(self, agent_id: str):
        """Perform health check on an agent"""
        try:
            agent = self.agents[agent_id]
            health_status = await agent.health_check()

            # Update performance score based on health
            if health_status.get('status') == 'healthy':
                self.agent_status[agent_id].performance_score = min(100.0,
                    self.agent_status[agent_id].performance_score + 1)
            else:
                self.agent_status[agent_id].performance_score = max(0.0,
                    self.agent_status[agent_id].performance_score - 5)

        except Exception as e:
            self.logger.error(f"Health check failed for {agent_id}: {e}")
            self.agent_status[agent_id].performance_score = max(0.0,
                self.agent_status[agent_id].performance_score - 10)

    async def get_agent_status(self) -> Dict[str, Any]:
        """Get overall agent corps status"""
        total_agents = len(self.agents)
        active_agents = sum(1 for status in self.agent_status.values() if status.status == AgentStatusEnum.PROCESSING)
        idle_agents = sum(1 for status in self.agent_status.values() if status.status == AgentStatusEnum.IDLE)

        domain_breakdown = {}
        for status in self.agent_status.values():
            domain = status.domain.value
            if domain not in domain_breakdown:
                domain_breakdown[domain] = {'total': 0, 'active': 0, 'idle': 0}
            domain_breakdown[domain]['total'] += 1
            if status.status == 'busy':
                domain_breakdown[domain]['active'] += 1
            elif status.status == 'idle':
                domain_breakdown[domain]['idle'] += 1

        return {
            'total_agents': total_agents,
            'active_agents': active_agents,
            'idle_agents': idle_agents,
            'queued_tasks': len(self.task_queue),
            'completed_tasks_today': len([
                task for task in self.completed_tasks
                if task.completed_at and task.completed_at.date() == datetime.now().date()
            ]),
            'domain_breakdown': domain_breakdown,
            'average_performance': sum(s.performance_score for s in self.agent_status.values()) / total_agents
        }

    async def shutdown(self) -> bool:
        """Shutdown the Agent Corps"""
        try:
            self.logger.info("🛑 Shutting down Agent Corps")

            # Shutdown all agents
            shutdown_tasks = []
            for agent in self.agents.values():
                shutdown_tasks.append(agent.shutdown())

            await asyncio.gather(*shutdown_tasks, return_exceptions=True)

            return True

        except Exception as e:
            self.logger.error(f"❌ Agent Corps shutdown failed: {e}")
            return False
