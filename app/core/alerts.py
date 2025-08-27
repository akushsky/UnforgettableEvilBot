import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from config.logging_config import get_logger

logger = get_logger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(Enum):
    """Alert statuses"""

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


@dataclass
class Alert:
    """Class for representing an alert"""

    id: str
    title: str
    message: str
    severity: AlertSeverity
    source: str
    created_at: datetime
    status: AlertStatus = AlertStatus.ACTIVE
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


class AlertRule:
    """Rule for generating alerts"""

    def __init__(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        severity: AlertSeverity,
        title: str,
        message_template: str,
        cooldown_minutes: int = 5,
        tags: Optional[List[str]] = None,
    ):
        """Initialize alert rule.

        Args:
            name: Rule name.
            condition: Function to check if alert should trigger.
            severity: Alert severity level.
            title: Alert title.
            message_template: Template for alert message.
            cooldown_minutes: Minutes to wait before triggering again.
            tags: Optional tags for the alert.
        """
        self.name = name
        self.condition = condition
        self.severity = severity
        self.title = title
        self.message_template = message_template
        self.cooldown_minutes = cooldown_minutes
        self.tags = tags or []
        self.last_triggered: Optional[datetime] = None

    def should_trigger(self, data: Dict[str, Any]) -> bool:
        """Check if alert should trigger"""
        if not self.condition(data):
            return False

        # Check cooldown
        if self.last_triggered:
            cooldown_end = self.last_triggered + timedelta(
                minutes=self.cooldown_minutes
            )
            if datetime.utcnow() < cooldown_end:
                return False

        return True

    def create_alert(self, data: Dict[str, Any]) -> Alert:
        """Create alert based on data"""
        message = self.message_template.format(**data)

        alert = Alert(
            id=f"{self.name}_{int(time.time())}",
            title=self.title,
            message=message,
            severity=self.severity,
            source=self.name,
            created_at=datetime.utcnow(),
            tags=self.tags,
            metadata=data,
        )

        self.last_triggered = datetime.utcnow()
        return alert


class AlertManager:
    """Alert manager for managing notifications"""

    def __init__(self):
        """Initialize the class."""
        self.logger = get_logger(__name__)
        self.alerts: Dict[str, Alert] = {}
        self.rules: Dict[str, AlertRule] = {}
        self.notifiers: List[Callable[[Alert], None]] = []
        self.max_alerts = 1000

        # Predefined rules
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Setup predefined alert rules"""

        # Rule for high CPU usage
        self.add_rule(
            AlertRule(
                name="high_cpu_usage",
                condition=lambda data: data.get("cpu_usage", 0) > 80,
                severity=AlertSeverity.WARNING,
                title="High CPU Usage",
                message_template="CPU usage is {cpu_usage:.1f}%",
                cooldown_minutes=10,
                tags=["performance", "cpu"],
            )
        )

        # Rule for high memory usage
        self.add_rule(
            AlertRule(
                name="high_memory_usage",
                condition=lambda data: data.get("memory_usage", 0) > 85,
                severity=AlertSeverity.WARNING,
                title="High Memory Usage",
                message_template="Memory usage is {memory_usage:.1f}%",
                cooldown_minutes=10,
                tags=["performance", "memory"],
            )
        )

        # Rule for slow requests
        self.add_rule(
            AlertRule(
                name="slow_requests",
                condition=lambda data: data.get("avg_response_time", 0) > 2.0,
                severity=AlertSeverity.WARNING,
                title="Slow Response Times",
                message_template="Average response time is {avg_response_time:.2f}s",
                cooldown_minutes=5,
                tags=["performance", "response_time"],
            )
        )

        # Rule for database errors
        self.add_rule(
            AlertRule(
                name="database_errors",
                condition=lambda data: data.get("db_errors", 0) > 10,
                severity=AlertSeverity.ERROR,
                title="Database Errors",
                message_template="{db_errors} database errors detected",
                cooldown_minutes=5,
                tags=["database", "errors"],
            )
        )

        # Rule for external service unavailability
        self.add_rule(
            AlertRule(
                name="external_service_down",
                condition=lambda data: not data.get("openai_available", True)
                or not data.get("telegram_available", True),
                severity=AlertSeverity.CRITICAL,
                title="External Service Unavailable",
                message_template="External services unavailable: OpenAI={openai_available}, Telegram={telegram_available}",
                cooldown_minutes=2,
                tags=["external_services", "availability"],
            )
        )

        # Rule for low cache hit ratio
        self.add_rule(
            AlertRule(
                name="low_cache_hit_ratio",
                condition=lambda data: data.get("cache_hit_ratio", 1.0) < 0.5,
                severity=AlertSeverity.WARNING,
                title="Low Cache Hit Ratio",
                message_template="Cache hit ratio is {cache_hit_ratio:.2f}",
                cooldown_minutes=15,
                tags=["cache", "performance"],
            )
        )

    def add_rule(self, rule: AlertRule):
        """Add alert rule"""
        self.rules[rule.name] = rule
        self.logger.info(f"Added alert rule: {rule.name}")

    def add_notifier(self, notifier: Callable[[Alert], None]):
        """Add notifier"""
        self.notifiers.append(notifier)
        self.logger.info(f"Added alert notifier: {notifier.__name__}")

    def check_alerts(self, data: Dict[str, Any]) -> List[Alert]:
        """Checking rules and creating alerts"""
        new_alerts = []

        for rule in self.rules.values():
            if rule.should_trigger(data):
                alert = rule.create_alert(data)
                self.alerts[alert.id] = alert
                new_alerts.append(alert)

                # Send notifications
                self._send_notifications(alert)

                self.logger.warning(f"Alert triggered: {alert.title} - {alert.message}")

        # Limit the number of alerts
        if len(self.alerts) > self.max_alerts:
            self._cleanup_old_alerts()

        return new_alerts

    def _send_notifications(self, alert: Alert):
        """Sending notifications"""
        for notifier in self.notifiers:
            try:
                notifier(alert)
            except Exception as e:
                self.logger.error(
                    f"Failed to send notification via {notifier.__name__}: {e}"
                )

    def acknowledge_alert(self, alert_id: str, user: str):
        """Acknowledging an alert"""
        if alert_id in self.alerts:
            alert = self.alerts[alert_id]
            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_at = datetime.utcnow()
            alert.acknowledged_by = user
            self.logger.info(f"Alert {alert_id} acknowledged by {user}")

    def resolve_alert(self, alert_id: str):
        """Alert permission settings"""
        if alert_id in self.alerts:
            alert = self.alerts[alert_id]
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.utcnow()
            self.logger.info(f"Alert {alert_id} resolved")

    def get_active_alerts(
        self, severity: Optional[AlertSeverity] = None
    ) -> List[Alert]:
        """Get active alerts"""
        active_alerts = [
            alert
            for alert in self.alerts.values()
            if alert.status == AlertStatus.ACTIVE
        ]

        if severity:
            active_alerts = [
                alert for alert in active_alerts if alert.severity == severity
            ]

        return sorted(active_alerts, key=lambda x: x.created_at, reverse=True)

    def get_alerts_by_severity(self, severity: AlertSeverity) -> List[Alert]:
        """Get alerts by severity level"""
        return [alert for alert in self.alerts.values() if alert.severity == severity]

    def get_alerts_by_source(self, source: str) -> List[Alert]:
        """Get alerts by source"""
        return [alert for alert in self.alerts.values() if alert.source == source]

    def _cleanup_old_alerts(self):
        """Cleanup of old alerts"""
        # Delete resolved alerts older than 7 days
        cutoff_date = datetime.utcnow() - timedelta(days=7)
        alerts_to_remove = [
            alert_id
            for alert_id, alert in self.alerts.items()
            if alert.status == AlertStatus.RESOLVED
            and alert.resolved_at
            and alert.resolved_at < cutoff_date
        ]

        for alert_id in alerts_to_remove:
            del self.alerts[alert_id]

        if alerts_to_remove:
            self.logger.info(f"Cleaned up {len(alerts_to_remove)} old alerts")


# Global instance of the alert manager
alert_manager = AlertManager()


# Predefined notifiers
def log_notifier(alert: Alert):
    """Notifier for logging alerts"""
    logger.warning(
        f"ALERT [{alert.severity.value.upper()}] {alert.title}: {alert.message}"
    )


def console_notifier(alert: Alert):
    """Notifier for console output"""
    print(f"\n🚨 ALERT [{alert.severity.value.upper()}] {alert.title}")
    print(f"   {alert.message}")
    print(f"   Source: {alert.source}")
    print(f"   Time: {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def json_notifier(alert: Alert):
    """Notifier for JSON format"""
    alert_data = {
        "id": alert.id,
        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity.value,
        "source": alert.source,
        "created_at": alert.created_at.isoformat(),
        "tags": alert.tags,
        "metadata": alert.metadata,
    }
    print(json.dumps(alert_data, ensure_ascii=False))


# Register notifiers
alert_manager.add_notifier(log_notifier)
alert_manager.add_notifier(console_notifier)


# Helper functions for creating alerts
def create_alert(
    title: str,
    message: str,
    severity: AlertSeverity,
    source: str,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Alert:
    """Create an alert manually"""
    alert = Alert(
        id=f"manual_{int(time.time())}",
        title=title,
        message=message,
        severity=severity,
        source=source,
        created_at=datetime.utcnow(),
        tags=tags or [],
        metadata=metadata or {},
    )

    alert_manager.alerts[alert.id] = alert
    alert_manager._send_notifications(alert)

    return alert


def check_system_health(data: Dict[str, Any]) -> List[Alert]:
    """Check system health and create alerts"""
    return alert_manager.check_alerts(data)


def get_system_alerts() -> Dict[str, Any]:
    """Get system alert summary"""
    active_alerts = alert_manager.get_active_alerts()

    return {
        "total_alerts": len(alert_manager.alerts),
        "active_alerts": len(active_alerts),
        "alerts_by_severity": {
            severity.value: len(alert_manager.get_alerts_by_severity(severity))
            for severity in AlertSeverity
        },
        "recent_alerts": [
            {
                "id": alert.id,
                "title": alert.title,
                "severity": alert.severity.value,
                "source": alert.source,
                "created_at": alert.created_at.isoformat(),
                "tags": alert.tags,
            }
            for alert in active_alerts[:10]  # Last 10 active alerts
        ],
    }


def clear_all_alerts():
    """Clear all alerts"""
    alert_manager.alerts.clear()
    logger.info("All alerts cleared")


def clear_alerts_by_title(title_pattern: str):
    """Clear alerts by title pattern"""
    alerts_to_remove = []
    for alert_id, alert in alert_manager.alerts.items():
        if title_pattern.lower() in alert.title.lower():
            alerts_to_remove.append(alert_id)

    for alert_id in alerts_to_remove:
        del alert_manager.alerts[alert_id]

    logger.info(
        f"Cleared {len(alerts_to_remove)} alerts matching pattern: {title_pattern}"
    )
