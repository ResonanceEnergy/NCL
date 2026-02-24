"""
NCL Agent Enums - Shared enumerations for agent system
"""

from enum import Enum


class AgentDomain(Enum):
    """Doctrine domains for specialized agents"""
    IT_INFRASTRUCTURE = "it_infrastructure"  # Priority 21-45
    LEGAL_COMPLIANCE = "legal_compliance"   # Priority 46-70
    HEALTH_WELLNESS = "health_wellness"     # Priority 71-95 (was HEALTH_MONITORING)
    INTEL_ANALYSIS = "intel_analysis"       # Priority 96-120 (was INTELLIGENCE_ANALYSIS)
    PLANNING_STRATEGY = "planning_strategy" # Priority 121-145 (was STRATEGIC_PLANNING)
    NETWORK_ENGINEERING = "network_engineering"  # Priority 146-170 (was NPE)
    AI_RESEARCH = "ai_research"  # Priority 171-195 (was AIN)
    FINANCIAL_OPTIMIZATION = "financial_optimization"  # Priority 196-220 (was FAO)
    RELATIONSHIP_MANAGEMENT = "relationship_management"  # Priority 221-245 (was RNN)
    TIME_ALLOCATION = "time_allocation"  # Priority 246-270 (was TAA)
    KNOWLEDGE_DEVELOPMENT = "knowledge_development"  # Priority 271-295 (was KDD)
    HIRING_RECRUITMENT = "hiring_recruitment"  # Priority 296-320
    TRAINING_DEVELOPMENT = "training_development"  # Priority 321-345
    SOP_DOCUMENTATION = "sop_documentation"  # Priority 346-370
    AUTOMATION_TOOLS = "automation_tools"  # Priority 371-395
    CEO_GOVERNANCE = "ceo_governance"  # Priority 396-420
    FATHERHOOD_FAMILY = "fatherhood_family"  # Priority 421-445


class AgentStatus(Enum):
    """Agent operational status"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    IDLE = "idle"
    PROCESSING = "processing"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class TaskPriority(Enum):
    """Task priority levels"""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    BACKGROUND = 5


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
