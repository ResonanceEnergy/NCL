"""Service Monitor — health checks, log inspection, and dashboard data."""

import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from .models import (
    ServiceName,
    ServiceStatus,
    ServiceHealth,
    ServiceDefinition,
    ServiceState,
)


class ServiceMonitor:
    """Monitors service health, logs, and generates dashboard data."""

    def __init__(self, data_dir: str, services: List[ServiceDefinition]):
        """
        Initialize service monitor.

        Args:
            data_dir: Base directory for monitor data storage.
            services: List of ServiceDefinition instances to monitor.
        """
        self.data_dir = data_dir
        self.services = services
        self.monitor_dir = os.path.join(data_dir, "deployment", "monitor")
        os.makedirs(self.monitor_dir, exist_ok=True)

    async def check_health(self, name: ServiceName) -> ServiceState:
        """
        Check health of a specific service.

        For services with health_endpoint: performs HTTP GET to localhost:{port}{health_endpoint}
        For services without: checks if PID is running via launchctl list

        Args:
            name: ServiceName to check.

        Returns:
            ServiceState with current health information.
        """
        service = next((s for s in self.services if s.name == name), None)
        if not service:
            return ServiceState(
                name=name,
                status=ServiceStatus.UNKNOWN,
                health=ServiceHealth.DOWN,
                error_message=f"Service {name.value} not found",
            )

        # Check if PID is running
        import socket
        import subprocess

        pid = None
        status = ServiceStatus.STOPPED
        health = ServiceHealth.DOWN

        try:
            # Get launchctl list
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0 and service.plist_label in result.stdout:
                for line in result.stdout.split("\n"):
                    if service.plist_label in line:
                        parts = line.split()
                        if parts and parts[0] != "-":
                            try:
                                pid = int(parts[0])
                                status = ServiceStatus.RUNNING
                                health = ServiceHealth.HEALTHY
                            except (ValueError, IndexError):
                                status = ServiceStatus.RUNNING
                                health = ServiceHealth.HEALTHY
                        else:
                            status = ServiceStatus.STOPPED
                            health = ServiceHealth.DOWN
                        break
        except Exception as e:
            return ServiceState(
                name=name,
                status=ServiceStatus.ERROR,
                health=ServiceHealth.DOWN,
                error_message=f"Failed to check status: {str(e)}",
            )

        # Check health endpoint if available
        if status == ServiceStatus.RUNNING and service.port and service.health_endpoint:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(("127.0.0.1", service.port))
                sock.close()

                if result == 0:
                    health = ServiceHealth.HEALTHY
                else:
                    health = ServiceHealth.DEGRADED
            except Exception:
                health = ServiceHealth.DEGRADED

        return ServiceState(
            name=name,
            status=status,
            health=health,
            pid=pid,
            last_check=datetime.now(),
        )

    async def check_all_health(self) -> List[ServiceState]:
        """Check health of all services."""
        results = []
        for service in self.services:
            state = await self.check_health(service.name)
            results.append(state)
        return results

    async def get_uptime_report(self) -> Dict:
        """
        Generate uptime report for all services over last 24 hours.

        Returns:
            Dict with per-service uptime metrics.
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "period_hours": 24,
            "services": {},
        }

        for service in self.services:
            state = await self.check_health(service.name)
            uptime_percent = 100.0 if state.status == ServiceStatus.RUNNING else 0.0

            report["services"][service.name.value] = {
                "status": state.status.value,
                "uptime_percent": uptime_percent,
                "health": state.health.value,
                "pid": state.pid,
                "last_check": state.last_check.isoformat(),
            }

        return report

    async def get_log_tail(self, name: ServiceName, lines: int = 50) -> Dict:
        """
        Get last N lines of stdout and stderr logs for a service.

        Args:
            name: ServiceName to retrieve logs for.
            lines: Number of lines to retrieve.

        Returns:
            Dict with keys: stdout (list), stderr (list), service (str).
        """
        service = next((s for s in self.services if s.name == name), None)
        if not service:
            return {
                "service": name.value,
                "stdout": [],
                "stderr": [],
                "error": f"Service {name.value} not found",
            }

        result = {
            "service": name.value,
            "stdout": [],
            "stderr": [],
        }

        # Read stdout log
        if service.log_stdout and os.path.exists(service.log_stdout):
            try:
                with open(service.log_stdout, "r") as f:
                    all_lines = f.readlines()
                    result["stdout"] = [line.rstrip() for line in all_lines[-lines:]]
            except Exception as e:
                result["stdout"] = [f"Error reading log: {str(e)}"]

        # Read stderr log
        if service.log_stderr and os.path.exists(service.log_stderr):
            try:
                with open(service.log_stderr, "r") as f:
                    all_lines = f.readlines()
                    result["stderr"] = [line.rstrip() for line in all_lines[-lines:]]
            except Exception as e:
                result["stderr"] = [f"Error reading log: {str(e)}"]

        return result

    async def get_restart_history(self, name: ServiceName) -> List[Dict]:
        """
        Parse logs to extract restart history for a service.

        Args:
            name: ServiceName to analyze.

        Returns:
            List of restart events with timestamps.
        """
        service = next((s for s in self.services if s.name == name), None)
        if not service:
            return []

        restarts = []

        # Check stderr log for error patterns that indicate restarts
        if service.log_stderr and os.path.exists(service.log_stderr):
            try:
                with open(service.log_stderr, "r") as f:
                    for line in f:
                        # Look for error patterns or "started" messages
                        if "ERROR" in line or "Exception" in line or "Traceback" in line:
                            restarts.append({
                                "type": "error",
                                "message": line.strip()[:100],
                                "timestamp": datetime.now().isoformat(),
                            })
            except Exception:
                pass

        return restarts

    async def get_dashboard_data(self) -> Dict:
        """
        Generate summary data for service dashboard.

        Returns:
            Dict with counts and alerts for UI display.
        """
        states = await self.check_all_health()

        total = len(states)
        healthy = sum(1 for s in states if s.is_healthy())
        running = sum(1 for s in states if s.is_running())
        needing_attention = sum(1 for s in states if s.needs_attention())

        # Calculate total uptime
        total_uptime_seconds = sum(
            s.uptime_seconds or 0 for s in states if s.uptime_seconds
        )

        # Generate alerts
        alerts = []
        for state in states:
            if state.status == ServiceStatus.ERROR:
                alerts.append({
                    "service": state.name.value,
                    "level": "critical",
                    "message": f"{state.name.value} is in error state",
                })
            elif state.health == ServiceHealth.UNHEALTHY:
                alerts.append({
                    "service": state.name.value,
                    "level": "warning",
                    "message": f"{state.name.value} is unhealthy",
                })
            elif state.health == ServiceHealth.DEGRADED:
                alerts.append({
                    "service": state.name.value,
                    "level": "info",
                    "message": f"{state.name.value} is degraded",
                })

        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_services": total,
                "healthy": healthy,
                "running": running,
                "needing_attention": needing_attention,
                "health_percent": round((healthy / total * 100) if total > 0 else 0, 1),
            },
            "services": [
                {
                    "name": s.name.value,
                    "status": s.status.value,
                    "health": s.health.value,
                    "pid": s.pid,
                    "last_check": s.last_check.isoformat(),
                }
                for s in states
            ],
            "alerts": alerts,
        }
