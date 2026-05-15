"""launchd Deployment Models — service definitions and status tracking."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


class ServiceName(Enum):
    """Enumeration of NCL services managed by launchd."""
    NCL_BRAIN = "ncl-brain"
    PUMP_WATCHER = "pump-watcher"
    ORCHESTRATOR = "orchestrator"
    COUNCILS = "councils"


class ServiceStatus(Enum):
    """Current operational status of a service."""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"


class ServiceHealth(Enum):
    """Health assessment of a service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DOWN = "down"


@dataclass
class ServiceDefinition:
    """Configuration definition for a launchd service."""
    name: ServiceName
    plist_label: str
    plist_path: str
    description: str
    port: Optional[int] = None
    health_endpoint: Optional[str] = None
    log_stdout: str = ""
    log_stderr: str = ""
    keep_alive: bool = True
    run_at_load: bool = True

    def __post_init__(self):
        """Validate service definition."""
        if not self.plist_label:
            raise ValueError(f"Service {self.name} requires plist_label")
        if not self.plist_path:
            raise ValueError(f"Service {self.name} requires plist_path")


@dataclass
class ServiceState:
    """Current state and health information for a running service."""
    name: ServiceName
    status: ServiceStatus
    health: ServiceHealth
    pid: Optional[int] = None
    uptime_seconds: Optional[float] = None
    last_check: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None
    restart_count: int = 0

    def is_healthy(self) -> bool:
        """Check if service is in a healthy state."""
        return self.status == ServiceStatus.RUNNING and self.health == ServiceHealth.HEALTHY

    def is_running(self) -> bool:
        """Check if service process is active."""
        return self.status == ServiceStatus.RUNNING

    def needs_attention(self) -> bool:
        """Check if service requires intervention."""
        return (self.status == ServiceStatus.ERROR or
                self.health in (ServiceHealth.UNHEALTHY, ServiceHealth.DOWN))


@dataclass
class DeploymentConfig:
    """Configuration for the deployment manager."""
    ncl_root: str = "~/dev/NCL"
    log_dir: str = "logs"
    python_path: str = "/opt/homebrew/bin/python3"
    services: List[ServiceDefinition] = field(default_factory=list)

    def __post_init__(self):
        """Expand home directory paths."""
        import os
        self.ncl_root = os.path.expanduser(self.ncl_root)
        self.log_dir = os.path.expanduser(self.log_dir) if self.log_dir.startswith("~") else self.log_dir
        if not self.log_dir.startswith("/"):
            # Relative to NCL root
            self.log_dir = os.path.join(self.ncl_root, self.log_dir)

    def get_service(self, name: ServiceName) -> Optional[ServiceDefinition]:
        """Get service definition by name."""
        for service in self.services:
            if service.name == name:
                return service
        return None
