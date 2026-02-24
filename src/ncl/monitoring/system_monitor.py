# src/ncl/monitoring/system_monitor.py
"""
System Monitor
Comprehensive monitoring and metrics collection for NCL
"""

import asyncio
import logging
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import platform


class MetricType(Enum):
"""MetricType function/class."""

    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"

"""AlertSeverity function/class."""


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Metric:
    """Represents a system metric"""
    name: str
    value: float
    type: MetricType
    timestamp: datetime = field(default_factory=datetime.now)
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class Alert:
    """Represents a system alert"""
    id: str
    title: str
    description: str
    severity: AlertSeverity
    timestamp: datetime = field(default_factory=datetime.now)
    resolved: bool = False
    resolution_time: Optional[datetime] = None
    metric_name: Optional[str] = None
    threshold_value: Optional[float] = None
    actual_value: Optional[float] = None


@dataclass
class SystemMetrics:
    """Comprehensive system metrics"""
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    load_average: Optional[List[float]] = None
    process_count: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


class SystemMonitor:
    """
    System Monitor - Comprehensive monitoring for NCL

    Collects system metrics, monitors performance, and generates alerts
    """__init__ function/class."""

    according to the Master Doctrine monitoring requirements.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Metrics storage
        self.metrics_history: List[Metric] = []
        self.alerts: List[Alert] = []
        self.active_alerts: Dict[str, Alert] = {}

        # Monitoring settings
        self.collection_interval = timedelta(seconds=30)
        self.metrics_retention = timedelta(hours=24)
        self.alert_retention = timedelta(days=7)

        # Alert thresholds
        self.alert_thresholds = {
            'cpu_usage_percent': 80.0,
            'memory_usage_percent': 85.0,
            'disk_usage_percent': 90.0,
            'error_rate_percent': 5.0
        }

        # System info
        self.system_info = self._get_system_info()

    async def initialize(self) -> bool:
        """Initialize the monitoring system"""
        try:
            self.logger.info("📊 Initializing System Monitor...")

            # Initialize metrics collection
            await self._initialize_metrics_collection()

            # Start monitoring loops
            asyncio.create_task(self._continuous_metrics_collection())
            asyncio.create_task(self._continuous_alert_monitoring())

            self.logger.info("✅ System Monitor initialization complete")
            return True

        except Exception as e:
            self.logger.error(f"❌ System Monitor initialization failed: {e}")
            return False

    def _get_system_info(self) -> Dict[str, Any]:
        """Get basic system information"""
        return {
            'platform': platform.system(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'cpu_count': psutil.cpu_count(),
            'memory_total_gb': round(psutil.virtual_memory().total / (1024**3), 2)
        }

    async def _initialize_metrics_collection(self):
        """Initialize metrics collection systems"""
        # Collect initial baseline metrics
        initial_metrics = await self.collect_metrics()
        self.logger.info(f"📈 Initial metrics collected: CPU {initial_metrics['cpu_usage_percent']}%, "
                        f"Memory {initial_metrics['memory_usage_percent']}%")

    async def collect_metrics(self) -> Dict[str, Any]:
        """Collect comprehensive system metrics"""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memory metrics
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent

            # Network metrics
            network = psutil.net_io_counters()
            bytes_sent = network.bytes_sent
            bytes_recv = network.bytes_recv

            # Process metrics
            process_count = len(psutil.pids())

            # Load average (Unix-like systems)
            load_average = None
            try:
                load_average = list(psutil.getloadavg())
            except AttributeError:
                # Windows doesn't have getloadavg
                pass

            metrics = SystemMetrics(
                cpu_usage_percent=cpu_percent,
                memory_usage_percent=memory_percent,
                disk_usage_percent=disk_percent,
                network_bytes_sent=bytes_sent,
                network_bytes_recv=bytes_recv,
                load_average=load_average,
                process_count=process_count
            )

            # Store metrics
            await self._store_metrics(metrics)

            return {
                'cpu_usage_percent': cpu_percent,
                'memory_usage_percent': memory_percent,
                'disk_usage_percent': disk_percent,
                'network_bytes_sent': bytes_sent,
                'network_bytes_recv': bytes_recv,
                'load_average': load_average,
                'process_count': process_count,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            self.logger.error(f"Metrics collection error: {e}")
            return {}

    async def _store_metrics(self, metrics: SystemMetrics):
        """Store metrics in history"""
        # Store individual metrics
        metric_data = [
            Metric('cpu_usage_percent', metrics.cpu_usage_percent, MetricType.GAUGE,
                  metrics.timestamp, {'unit': 'percent'}),
            Metric('memory_usage_percent', metrics.memory_usage_percent, MetricType.GAUGE,
                  metrics.timestamp, {'unit': 'percent'}),
            Metric('disk_usage_percent', metrics.disk_usage_percent, MetricType.GAUGE,
                  metrics.timestamp, {'unit': 'percent'}),
            Metric('network_bytes_sent', metrics.network_bytes_sent, MetricType.COUNTER,
                  metrics.timestamp, {'unit': 'bytes'}),
            Metric('network_bytes_recv', metrics.network_bytes_recv, MetricType.COUNTER,
                  metrics.timestamp, {'unit': 'bytes'}),
            Metric('process_count', metrics.process_count, MetricType.GAUGE,
                  metrics.timestamp, {'unit': 'count'})
        ]

        self.metrics_history.extend(metric_data)

        # Maintain retention limit
        cutoff_time = datetime.now() - self.metrics_retention
        self.metrics_history = [
            m for m in self.metrics_history
            if m.timestamp > cutoff_time
        ]

    async def analyze_performance(self) -> Dict[str, Any]:
        """Analyze system performance trends"""
        try:
            # Get recent metrics (last hour)
            recent_metrics = [
                m for m in self.metrics_history
                if datetime.now() - m.timestamp < timedelta(hours=1)
            ]

            if not recent_metrics:
                return {'status': 'insufficient_data'}

            # Group metrics by name
            metrics_by_name = {}
            for metric in recent_metrics:
                if metric.name not in metrics_by_name:
                    metrics_by_name[metric.name] = []
                metrics_by_name[metric.name].append(metric.value)

            # Calculate trends
            analysis = {}
            for name, values in metrics_by_name.items():
                if len(values) >= 2:
                    current_avg = sum(values[-5:]) / min(5, len(values))  # Last 5 readings
                    previous_avg = sum(values[:-5]) / max(1, len(values) - 5) if len(values) > 5 else current_avg

                    trend = 'stable'
                    if current_avg > previous_avg * 1.1:
                        trend = 'increasing'
                    elif current_avg < previous_avg * 0.9:
                        trend = 'decreasing'

                    analysis[name] = {
                        'current_average': round(current_avg, 2),
                        'trend': trend,
                        'data_points': len(values)
                    }

            return {
                'status': 'analyzed',
                'analysis': analysis,
                'time_range': 'last_hour'
            }

        except Exception as e:
            self.logger.error(f"Performance analysis error: {e}")
            return {'status': 'error', 'message': str(e)}

    async def _continuous_metrics_collection(self):
        """Continuous metrics collection loop"""
        while True:
            try:
                await asyncio.sleep(self.collection_interval.total_seconds())
                await self.collect_metrics()
            except Exception as e:
                self.logger.error(f"Metrics collection loop error: {e}")
                await asyncio.sleep(10)  # Brief pause before retry

    async def _continuous_alert_monitoring(self):
        """Continuous alert monitoring loop"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._check_alert_conditions()
                await self._cleanup_old_alerts()
            except Exception as e:
                self.logger.error(f"Alert monitoring loop error: {e}")

    async def _check_alert_conditions(self):
        """Check for alert conditions"""
        try:
            # Get latest metrics
            latest_metrics = {}
            for metric in reversed(self.metrics_history):
                if metric.name not in latest_metrics:
                    latest_metrics[metric.name] = metric.value
                if len(latest_metrics) == len(self.alert_thresholds):
                    break

            # Check each threshold
            for metric_name, threshold in self.alert_thresholds.items():
                if metric_name in latest_metrics:
                    current_value = latest_metrics[metric_name]

                    if current_value > threshold:
                        await self._generate_alert(
                            metric_name=metric_name,
                            threshold_value=threshold,
                            actual_value=current_value
                        )

        except Exception as e:
            self.logger.error(f"Alert condition check error: {e}")

    async def _generate_alert(self, metric_name: str, threshold_value: float, actual_value: float):
        """Generate an alert for threshold violation"""
        # Check if similar alert already exists
        alert_key = f"{metric_name}_{threshold_value}"
        if alert_key in self.active_alerts:
            return  # Alert already active

        # Determine severity
        severity = AlertSeverity.WARNING
        if actual_value > threshold_value * 1.5:
            severity = AlertSeverity.CRITICAL
        elif actual_value > threshold_value * 1.2:
            severity = AlertSeverity.ERROR

        # Create alert
        alert = Alert(
            id=f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            title=f"High {metric_name.replace('_', ' ').title()}",
            description=f"{metric_name} is at {actual_value:.1f}%, exceeding threshold of {threshold_value}%",
            severity=severity,
            metric_name=metric_name,
            threshold_value=threshold_value,
            actual_value=actual_value
        )

        self.alerts.append(alert)
        self.active_alerts[alert_key] = alert

        self.logger.warning(f"🚨 Alert generated: {alert.title}")

    async def _cleanup_old_alerts(self):
        """Clean up old alerts"""
        cutoff_time = datetime.now() - self.alert_retention

        # Remove old alerts
        self.alerts = [
            alert for alert in self.alerts
            if alert.timestamp > cutoff_time
        ]

    async def get_metrics_history(self, metric_name: Optional[str] = None,
                                time_range: timedelta = timedelta(hours=1)) -> List[Metric]:
        """Get metrics history"""
        cutoff_time = datetime.now() - time_range

        metrics = [
            m for m in self.metrics_history
            if m.timestamp > cutoff_time
        ]

        if metric_name:
            metrics = [m for m in metrics if m.name == metric_name]

        return metrics

    async def get_active_alerts(self) -> List[Alert]:
        """Get currently active alerts"""
        return list(self.active_alerts.values())

    async def resolve_alert(self, alert_id: str, resolution_note: str = "") -> bool:
        """Resolve an alert"""
        for alert in self.alerts:
            if alert.id == alert_id and not alert.resolved:
                alert.resolved = True
                alert.resolution_time = datetime.now()
                # Remove from active alerts
                for key, active_alert in self.active_alerts.items():
                    if active_alert.id == alert_id:
                        del self.active_alerts[key]
                        break
                self.logger.info(f"✅ Alert resolved: {alert.title}")
                return True
        return False

    async def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health assessment"""
        try:
            # Get latest metrics
            latest_metrics = await self.collect_metrics()

            # Count active alerts
            active_alerts = len(self.active_alerts)

            # Calculate health score (0-100)
            health_score = 100.0

            # Deduct points for high resource usage
            if latest_metrics.get('cpu_usage_percent', 0) > 80:
                health_score -= 20
            if latest_metrics.get('memory_usage_percent', 0) > 85:
                health_score -= 25
            if latest_metrics.get('disk_usage_percent', 0) > 90:
                health_score -= 30

            # Deduct points for active alerts
            health_score -= active_alerts * 10

            health_score = max(0, min(100, health_score))

            # Determine health status
            if health_score >= 90:
                status = 'excellent'
            elif health_score >= 75:
                status = 'good'
            elif health_score >= 60:
                status = 'fair'
            elif health_score >= 40:
                status = 'poor'
            else:
                status = 'critical'

            return {
                'health_score': round(health_score, 1),
                'status': status,
                'active_alerts': active_alerts,
                'latest_metrics': latest_metrics,
                'system_info': self.system_info
            }

        except Exception as e:
            self.logger.error(f"Health assessment error: {e}")
            return {
                'health_score': 0,
                'status': 'unknown',
                'error': str(e)
            }

    async def shutdown(self) -> bool:
        """Shutdown the monitoring system"""
        try:
            self.logger.info("🛑 Shutting down System Monitor")
            # Save final metrics if needed
            return True
        except Exception as e:
            self.logger.error(f"❌ Monitor shutdown failed: {e}")
            return False
