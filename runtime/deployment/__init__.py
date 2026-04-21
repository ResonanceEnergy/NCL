"""NCL launchd Deployment and Monitoring System.

This module provides comprehensive service management for NCL daemon services:
- DeploymentManager: Install, uninstall, start, stop, and restart services
- ServiceMonitor: Health checks, log inspection, uptime tracking
- ServiceStatus: Operational status enum
"""

from .models import (
    ServiceName,
    ServiceStatus,
    ServiceHealth,
    ServiceDefinition,
    ServiceState,
    DeploymentConfig,
)
from .manager import DeploymentManager
from .monitor import ServiceMonitor

__all__ = [
    "DeploymentManager",
    "ServiceMonitor",
    "ServiceStatus",
    "ServiceName",
    "ServiceHealth",
    "ServiceDefinition",
    "ServiceState",
    "DeploymentConfig",
]

__version__ = "1.0.0"
