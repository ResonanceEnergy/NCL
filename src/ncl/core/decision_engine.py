# src/ncl/core/decision_engine.py
"""
Decision Engine
Processes insights and makes decisions according to Master Doctrine v2.0
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from .digital_twin import DigitalTwin
from .memory_system import MemorySystem


class DecisionType(Enum):
"""DecisionType function/class."""

    OPERATIONAL = "operational"
    STRATEGIC = "strategic"
    EMERGENCY = "emergency"
    EVOLUTIONARY = "evolutionary"

"""DecisionPriority function/class."""


class DecisionPriority(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Decision:
    """Represents a decision made by the system"""
    id: str
    type: DecisionType
    priority: DecisionPriority
    title: str
    description: str
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    implemented: bool = False
    outcome: Optional[str] = None


@dataclass
class DecisionContext:
    """Context for decision making"""
    insight_type: str
    severity: str
    affected_components: List[str]
    historical_precedence: List[Decision]
    doctrine_alignment: float  # 0-1 scale
    risk_assessment: Dict[str, Any]


class DecisionEngine:
    """
    Decision Engine - Processes insights and makes doctrine-aligned decisions

    Implements the decision framework from Master Doctrine v2.0, ensuring
    """__init__ function/class."""

    all decisions are evidence-based, risk-assessed, and doctrine-compliant.
    """

    def __init__(self, digital_twin: DigitalTwin, memory_system: MemorySystem):
        self.logger = logging.getLogger(__name__)
        self.digital_twin = digital_twin
        self.memory_system = memory_system

        # Decision tracking
        self.active_decisions: Dict[str, Decision] = {}
        self.decision_history: List[Decision] = []

        # Decision thresholds
        self.critical_threshold = 0.8  # Doctrine alignment required for critical decisions
        self.emergency_threshold = 0.9  # Higher threshold for emergency decisions

        # Decision templates
        self.decision_templates = self._load_decision_templates()

    def _load_decision_templates(self) -> Dict[str, Dict[str, Any]]:
        """Load decision templates from doctrine"""
        return {
            'component_health': {
                'type': DecisionType.OPERATIONAL,
                'template': 'Component {component} health at {health:.1f}%',
                'evidence_required': ['health_metrics', 'trend_analysis'],
                'risk_factors': ['system_stability', 'dependency_impact']
            },
            'dependency_risk': {
                'type': DecisionType.STRATEGIC,
                'template': 'Dependency risk between {component} and {dependency}',
                'evidence_required': ['relationship_analysis', 'impact_assessment'],
                'risk_factors': ['cascade_failure', 'performance_degradation']
            },
            'system_optimization': {
                'type': DecisionType.EVOLUTIONARY,
                'template': 'System optimization opportunity identified',
                'evidence_required': ['performance_metrics', 'resource_analysis'],
                'risk_factors': ['implementation_complexity', 'downtime_risk']
            },
            'security_threat': {
                'type': DecisionType.EMERGENCY,
                'template': 'Security threat detected: {threat_type}',
                'evidence_required': ['threat_intelligence', 'impact_analysis'],
                'risk_factors': ['data_breach', 'system_compromise']
            }
        }

    async def initialize(self) -> bool:
        """Initialize the decision engine"""
        try:
            self.logger.info("🔄 Initializing Decision Engine...")

            # Load decision history
            await self._load_decision_history()

            # Validate decision templates
            await self._validate_templates()

            self.logger.info("✅ Decision Engine initialization complete")
            return True

        except Exception as e:
            self.logger.error(f"❌ Decision Engine initialization failed: {e}")
            return False

    async def _load_decision_history(self):
        """Load historical decisions from memory"""
        try:
            history_data = await self.memory_system.retrieve("decision_history")
            if history_data:
                for decision_data in history_data:
                    decision = Decision(**decision_data)
                    self.decision_history.append(decision)

                self.logger.info(f"Loaded {len(self.decision_history)} historical decisions")

        except Exception as e:
            self.logger.warning(f"Could not load decision history: {e}")

    async def _validate_templates(self):
        """Validate decision templates against doctrine"""
        # Ensure all templates have required fields
        required_fields = ['type', 'template', 'evidence_required', 'risk_factors']

        for template_name, template in self.decision_templates.items():
            missing_fields = [field for field in required_fields if field not in template]
            if missing_fields:
                self.logger.warning(f"Template {template_name} missing fields: {missing_fields}")

    async def process_insight(self, insight: Dict[str, Any]) -> Optional[Decision]:
        """Process an insight and generate a decision if warranted"""
        try:
            # Create decision context
            context = await self._create_decision_context(insight)

            # Assess decision necessity
            if not await self._should_make_decision(context):
                return None

            # Generate decision
            decision = await self._generate_decision(insight, context)

            # Validate decision against doctrine
            if await self._validate_decision(decision, context):
                # Store decision
                self.active_decisions[decision.id] = decision
                await self._save_decision(decision)

                self.logger.info(f"🎯 Generated decision: {decision.title}")
                return decision

            return None

        except Exception as e:
            self.logger.error(f"❌ Failed to process insight: {e}")
            return None

    async def process_threat(self, threat: Dict[str, Any]) -> Optional[Decision]:
        """Process a security threat with emergency priority"""
        # Threats always generate decisions
        insight = {
            'type': 'security_threat',
            'threat_type': threat.get('type', 'unknown'),
            'severity': threat.get('severity', 'high'),
            'description': threat.get('description', ''),
            'evidence': threat.get('evidence', [])
        }

        return await self.process_insight(insight)

    async def _create_decision_context(self, insight: Dict[str, Any]) -> DecisionContext:
        """Create context for decision making"""
        insight_type = insight.get('type', 'unknown')

        # Get affected components
        affected_components = insight.get('affected_components', [])
        if 'component' in insight:
            affected_components.append(insight['component'])

        # Find historical precedence
        historical_precedence = [
            d for d in self.decision_history
            if d.type.value == insight_type and any(comp in str(d.description) for comp in affected_components)
        ][:5]  # Limit to 5 most recent

        # Assess doctrine alignment
        doctrine_alignment = await self._assess_doctrine_alignment(insight)

        # Risk assessment
        risk_assessment = await self._assess_risks(insight)

        return DecisionContext(
            insight_type=insight_type,
            severity=insight.get('severity', 'medium'),
            affected_components=affected_components,
            historical_precedence=historical_precedence,
            doctrine_alignment=doctrine_alignment,
            risk_assessment=risk_assessment
        )

    async def _assess_doctrine_alignment(self, insight: Dict[str, Any]) -> float:
        """Assess how well the insight aligns with doctrine principles"""
        # Simplified alignment assessment
        alignment_score = 0.8  # Base alignment

        # Adjust based on insight type
        if insight.get('type') == 'component_health':
            alignment_score = 0.9  # Health monitoring is core doctrine
        elif insight.get('type') == 'security_threat':
            alignment_score = 0.95  # Security is paramount
        elif insight.get('type') == 'system_optimization':
            alignment_score = 0.85  # Optimization supports evolution

        return alignment_score

    async def _assess_risks(self, insight: Dict[str, Any]) -> Dict[str, Any]:
        """Assess risks associated with the insight"""
        risk_levels = {
            'low': 0.2,
            'medium': 0.5,
            'high': 0.8,
            'critical': 0.95
        }

        severity = insight.get('severity', 'medium')
        base_risk = risk_levels.get(severity, 0.5)

        return {
            'overall_risk': base_risk,
            'impact_areas': ['system_stability', 'performance', 'security'],
            'mitigation_required': base_risk > 0.7
        }

    async def _should_make_decision(self, context: DecisionContext) -> bool:
        """Determine if a decision should be made"""
        # Always make decisions for critical severity
        if context.severity == 'critical':
            return True

        # Make decisions for high severity with good doctrine alignment
        if context.severity == 'high' and context.doctrine_alignment > 0.7:
            return True

        # Make decisions for medium severity with strong evidence
        if context.severity == 'medium' and len(context.historical_precedence) > 0:
            return True

        return False

    async def _generate_decision(self, insight: Dict[str, Any], context: DecisionContext) -> Decision:
        """Generate a decision based on insight and context"""
        template = self.decision_templates.get(context.insight_type, self.decision_templates['component_health'])

        # Generate decision ID
        decision_id = f"{context.insight_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create title and description
        title = template['template'].format(**insight)
        description = insight.get('message', insight.get('description', 'Decision generated from system insight'))

        # Determine priority
        priority = self._calculate_priority(context)

        # Gather evidence
        evidence = await self._gather_evidence(insight, template)

        # Generate recommendations
        recommendations = await self._generate_recommendations(insight, context)

        # Assess risks
        risks = await self._assess_decision_risks(insight, template)

        return Decision(
            id=decision_id,
            type=template['type'],
            priority=priority,
            title=title,
            description=description,
            evidence=evidence,
            recommendations=recommendations,
            risks=risks
        )

    def _calculate_priority(self, context: DecisionContext) -> DecisionPriority:
        """Calculate decision priority"""
        if context.severity == 'critical':
            return DecisionPriority.CRITICAL
        elif context.severity == 'high':
            return DecisionPriority.HIGH
        elif context.doctrine_alignment > 0.8:
            return DecisionPriority.HIGH
        elif context.risk_assessment['overall_risk'] > 0.7:
            return DecisionPriority.MEDIUM
        else:
            return DecisionPriority.LOW

    async def _gather_evidence(self, insight: Dict[str, Any], template: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Gather evidence for the decision"""
        evidence = []

        # Add insight as primary evidence
        evidence.append({
            'type': 'insight',
            'source': 'system_monitoring',
            'data': insight,
            'timestamp': datetime.now()
        })

        # Add historical evidence if available
        for req in template['evidence_required']:
            hist_evidence = await self._get_historical_evidence(req, insight)
            if hist_evidence:
                evidence.extend(hist_evidence)

        return evidence

    async def _get_historical_evidence(self, evidence_type: str, insight: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get historical evidence of the specified type"""
        # In real implementation, this would query historical data
        return [{
            'type': evidence_type,
            'source': 'historical_data',
            'description': f'Historical {evidence_type} for {insight.get("component", "system")}',
            'timestamp': datetime.now()
        }]

    async def _generate_recommendations(self, insight: Dict[str, Any], context: DecisionContext) -> List[str]:
        """Generate recommendations for the decision"""
        recommendations = []

        insight_type = insight.get('type')

        if insight_type == 'component_health':
            health_score = insight.get('health_score', 100)
            if health_score < 50:
                recommendations.append("Immediate intervention required - escalate to emergency protocol")
                recommendations.append("Isolate component to prevent cascade failure")
            elif health_score < 70:
                recommendations.append("Schedule maintenance within 24 hours")
                recommendations.append("Increase monitoring frequency")
            else:
                recommendations.append("Monitor component health trends")
                recommendations.append("Review maintenance schedule")

        elif insight_type == 'dependency_risk':
            recommendations.append("Strengthen dependency relationships")
            recommendations.append("Implement redundancy measures")
            recommendations.append("Review system architecture for decoupling opportunities")

        elif insight_type == 'security_threat':
            recommendations.append("Activate security protocols immediately")
            recommendations.append("Isolate affected systems")
            recommendations.append("Notify security team and initiate incident response")

        return recommendations

    async def _assess_decision_risks(self, insight: Dict[str, Any], template: Dict[str, Any]) -> List[str]:
        """Assess risks associated with implementing the decision"""
        risks = []

        for risk_factor in template['risk_factors']:
            if risk_factor == 'system_stability':
                risks.append("Potential temporary system instability during implementation")
            elif risk_factor == 'dependency_impact':
                risks.append("May affect dependent components and services")
            elif risk_factor == 'performance_degradation':
                risks.append("Temporary performance impact expected")
            elif risk_factor == 'cascade_failure':
                risks.append("Risk of cascade failure if not implemented carefully")
            elif risk_factor == 'implementation_complexity':
                risks.append("Complex implementation may require extended downtime")
            elif risk_factor == 'downtime_risk':
                risks.append("Service downtime may be required")

        return risks

    async def _validate_decision(self, decision: Decision, context: DecisionContext) -> bool:
        """Validate decision against doctrine requirements"""
        # Check doctrine alignment
        if decision.type == DecisionType.EMERGENCY and context.doctrine_alignment < self.emergency_threshold:
            return False
        elif decision.priority == DecisionPriority.CRITICAL and context.doctrine_alignment < self.critical_threshold:
            return False

        # Check evidence requirements
        template = self.decision_templates.get(context.insight_type)
        if template:
            required_evidence = template['evidence_required']
            provided_evidence_types = [ev['type'] for ev in decision.evidence]
            missing_evidence = [req for req in required_evidence if req not in provided_evidence_types]

            if missing_evidence:
                self.logger.warning(f"Decision missing required evidence: {missing_evidence}")
                return False

        return True

    async def _save_decision(self, decision: Decision):
        """Save decision to memory and history"""
        # Add to history
        self.decision_history.append(decision)

        # Keep only recent history (last 1000 decisions)
        if len(self.decision_history) > 1000:
            self.decision_history = self.decision_history[-1000:]

        # Save to memory system
        history_data = [
            {
                'id': d.id,
                'type': d.type.value,
                'priority': d.priority.value,
                'title': d.title,
                'description': d.description,
                'evidence': d.evidence,
                'recommendations': d.recommendations,
                'risks': d.risks,
                'created_at': d.created_at.isoformat(),
                'implemented': d.implemented,
                'outcome': d.outcome
            }
            for d in self.decision_history[-100:]  # Save last 100 decisions
        ]

        await self.memory_system.store("decision_history", history_data)

    async def get_decision_status(self, decision_id: str) -> Optional[Decision]:
        """Get status of a specific decision"""
        return self.active_decisions.get(decision_id)

    async def implement_decision(self, decision_id: str, outcome: str = None) -> bool:
        """Mark a decision as implemented"""
        decision = self.active_decisions.get(decision_id)
        if decision:
            decision.implemented = True
            decision.outcome = outcome
            await self._save_decision(decision)
            return True
        return False

    async def get_decision_history(self, limit: int = 50) -> List[Decision]:
        """Get recent decision history"""
        return self.decision_history[-limit:]

    async def shutdown(self) -> bool:
        """Shutdown the decision engine"""
        try:
            self.logger.info("🛑 Shutting down Decision Engine")
            # Save any pending decisions
            for decision in self.active_decisions.values():
                if not decision.implemented:
                    await self._save_decision(decision)
            return True
        except Exception as e:
            self.logger.error(f"❌ Decision Engine shutdown failed: {e}")
            return False
