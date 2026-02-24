# src/ncl/agents/base_agent.py
"""
Base Agent
Foundation class for all NCL agents
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .enums import AgentDomain


@dataclass
class AgentCapabilities:
    """Capabilities of an agent"""
    skills: List[str]
    domains: List[str]
    max_concurrent_tasks: int = 1
    response_time_sla: int = 300  # seconds
    accuracy_requirement: float = 0.95


class BaseAgent(ABC):
    """
    Base Agent - Foundation for all NCL specialized agents

    Provides common functionality and interface for all agents
    in the Agent Corps Super-Pump.
    """

    def __init__(self, agent_id: str, domain: AgentDomain, capabilities: List[str]):
    """__init__ function/class."""

        self.agent_id = agent_id
        self.domain = domain
        self.capabilities = capabilities

        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Agent state
        self.is_active = False
        self.last_activity = None
        self.tasks_completed = 0
        self.performance_metrics = {
            'response_time_avg': 0.0,
            'accuracy_score': 1.0,
            'tasks_completed': 0,
            'errors_count': 0
        }

        # Task management
        self.current_tasks: List[Dict[str, Any]] = []
        self.task_history: List[Dict[str, Any]] = []

    async def initialize(self) -> bool:
        """Initialize the agent"""
        try:
            self.logger.info(f"🤖 Initializing agent {self.agent_id} for domain {self.domain.value}")

            # Initialize domain-specific components
            await self._initialize_domain_components()

            self.is_active = True
            self.last_activity = datetime.now()

            self.logger.info(f"✅ Agent {self.agent_id} initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"❌ Agent {self.agent_id} initialization failed: {e}")
            return False

    @abstractmethod
    async def _initialize_domain_components(self):
        """Initialize domain-specific components"""
        pass

    async def gather_intelligence(self) -> List[Dict[str, Any]]:
        """Gather intelligence specific to this agent's domain"""
        try:
            # Base intelligence gathering
            intelligence = await self._gather_domain_intelligence()

            # Add agent metadata
            for item in intelligence:
                item['source_agent'] = self.agent_id
                item['domain'] = self.domain.value
                item['timestamp'] = datetime.now().isoformat()

            return intelligence

        except Exception as e:
            self.logger.error(f"Intelligence gathering failed for {self.agent_id}: {e}")
            return []

    @abstractmethod
    async def _gather_domain_intelligence(self) -> List[Dict[str, Any]]:
        """Gather intelligence specific to the agent's domain"""
        pass

    async def execute_task(self, task_description: str) -> Dict[str, Any]:
        """Execute a task"""
        start_time = datetime.now()

        try:
            self.logger.info(f"🎯 Agent {self.agent_id} executing task: {task_description[:50]}...")

            # Check if agent can handle this task
            if not await self._can_handle_task(task_description):
                return {
                    'status': 'rejected',
                    'reason': 'Task outside agent capabilities',
                    'agent_id': self.agent_id
                }

            # Check current task load
            if len(self.current_tasks) >= 1:  # Max 1 concurrent task per agent
                return {
                    'status': 'queued',
                    'reason': 'Agent at capacity',
                    'agent_id': self.agent_id
                }

            # Add to current tasks
            task_info = {
                'description': task_description,
                'started_at': start_time,
                'status': 'in_progress'
            }
            self.current_tasks.append(task_info)

            # Execute the task
            result = await self._execute_domain_task(task_description)

            # Update task info
            task_info['completed_at'] = datetime.now()
            task_info['status'] = 'completed'
            task_info['result'] = result

            # Move to history
            self.task_history.append(task_info)
            self.current_tasks.remove(task_info)

            # Update metrics
            execution_time = (datetime.now() - start_time).total_seconds()
            self._update_performance_metrics(execution_time, True)

            self.tasks_completed += 1
            self.last_activity = datetime.now()

            return {
                'status': 'completed',
                'result': result,
                'execution_time': execution_time,
                'agent_id': self.agent_id
            }

        except Exception as e:
            self.logger.error(f"Task execution failed for {self.agent_id}: {e}")

            # Update failed task
            if self.current_tasks:
                failed_task = self.current_tasks[-1]
                failed_task['status'] = 'failed'
                failed_task['error'] = str(e)
                self.task_history.append(failed_task)
                self.current_tasks.remove(failed_task)

            # Update metrics
            execution_time = (datetime.now() - start_time).total_seconds()
            self._update_performance_metrics(execution_time, False)

            return {
                'status': 'failed',
                'error': str(e),
                'execution_time': execution_time,
                'agent_id': self.agent_id
            }

    @abstractmethod
    async def _execute_domain_task(self, task_description: str) -> Any:
        """Execute a domain-specific task"""
        pass

    async def _can_handle_task(self, task_description: str) -> bool:
        """Check if agent can handle a specific task"""
        # Simple capability matching
        task_lower = task_description.lower()

        capability_keywords = {
            'it_infrastructure': ['system', 'network', 'server', 'infrastructure', 'security', 'backup'],
            'legal_compliance': ['legal', 'compliance', 'contract', 'regulation', 'policy', 'law'],
            'health_wellness': ['health', 'wellness', 'fitness', 'medical', 'ergonomics', 'stress'],
            'intel_analysis': ['intelligence', 'analysis', 'threat', 'risk', 'security', 'monitoring'],
            'planning_strategy': ['planning', 'strategy', 'goal', 'resource', 'project', 'decision'],
            'hiring_recruitment': ['hiring', 'recruitment', 'candidate', 'interview', 'talent'],
            'training_development': ['training', 'development', 'skill', 'learning', 'coaching'],
            'sop_documentation': ['sop', 'documentation', 'process', 'procedure', 'workflow'],
            'automation_tools': ['automation', 'tool', 'script', 'integration', 'api'],
            'ceo_governance': ['governance', 'executive', 'leadership', 'strategy', 'oversight'],
            'fatherhood_family': ['family', 'parenting', 'balance', 'relationship', 'fatherhood']
        }

        domain_keywords = capability_keywords.get(self.domain.value, [])

        return any(keyword in task_lower for keyword in domain_keywords)

    async def execute_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a decision from the Decision Engine"""
        try:
            decision_type = decision.get('type')
            decision_description = decision.get('description', '')

            # Convert decision to task
            task_description = f"Execute decision: {decision_description}"

            # Execute as task
            result = await self.execute_task(task_description)

            return {
                'agent_id': self.agent_id,
                'decision_id': decision.get('id'),
                'execution_result': result
            }

        except Exception as e:
            self.logger.error(f"Decision execution failed for {self.agent_id}: {e}")
            return {
                'agent_id': self.agent_id,
                'decision_id': decision.get('id'),
                'status': 'failed',
                'error': str(e)
            }

    def _update_performance_metrics(self, execution_time: float, success: bool):
        """Update agent performance metrics"""
        # Update response time (exponential moving average)
        alpha = 0.1
        self.performance_metrics['response_time_avg'] = (
            alpha * execution_time +
            (1 - alpha) * self.performance_metrics['response_time_avg']
        )

        # Update accuracy
        if success:
            self.performance_metrics['accuracy_score'] = min(1.0,
                self.performance_metrics['accuracy_score'] + 0.01)
        else:
            self.performance_metrics['errors_count'] += 1
            self.performance_metrics['accuracy_score'] = max(0.0,
                self.performance_metrics['accuracy_score'] - 0.05)

        self.performance_metrics['tasks_completed'] = self.tasks_completed

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the agent"""
        try:
            # Check basic functionality
            is_healthy = self.is_active and self.last_activity is not None

            # Check recent activity (within last hour)
            if self.last_activity:
                time_since_activity = datetime.now() - self.last_activity
                is_recently_active = time_since_activity.total_seconds() < 3600
            else:
                is_recently_active = False

            # Check task queue
            has_capacity = len(self.current_tasks) < 1

            health_status = 'healthy'
            if not is_healthy or not is_recently_active:
                health_status = 'degraded'
            elif not has_capacity:
                health_status = 'busy'

            return {
                'agent_id': self.agent_id,
                'status': health_status,
                'is_active': self.is_active,
                'last_activity': self.last_activity.isoformat() if self.last_activity else None,
                'current_tasks': len(self.current_tasks),
                'tasks_completed': self.tasks_completed,
                'performance_metrics': self.performance_metrics.copy(),
                'capabilities': self.capabilities.copy()
            }

        except Exception as e:
            self.logger.error(f"Health check failed for {self.agent_id}: {e}")
            return {
                'agent_id': self.agent_id,
                'status': 'unhealthy',
                'error': str(e)
            }

    async def get_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        return {
            'agent_id': self.agent_id,
            'domain': self.domain.value,
            'is_active': self.is_active,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'current_tasks': len(self.current_tasks),
            'tasks_completed': self.tasks_completed,
            'performance_score': self.performance_metrics['accuracy_score'] * 100,
            'capabilities': self.capabilities
        }

    async def shutdown(self) -> bool:
        """Shutdown the agent"""
        try:
            self.logger.info(f"🛑 Shutting down agent {self.agent_id}")

            # Complete any current tasks
            for task in self.current_tasks:
                task['status'] = 'cancelled'
                self.task_history.append(task)

            self.current_tasks.clear()
            self.is_active = False

            return True

        except Exception as e:
            self.logger.error(f"❌ Agent {self.agent_id} shutdown failed: {e}")
            return False
