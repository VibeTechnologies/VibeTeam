"""
Health Check Connector - Service health monitoring.

Monitors:
- API endpoints (response codes, latency)
- Service availability
- SSL certificate expiry
"""

import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class EndpointConfig(TypedDict):
    """Configuration for a health check endpoint."""

    name: str
    url: str
    critical: bool


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    url: str
    status: str  # healthy, degraded, down
    status_code: int | None
    latency_ms: float
    error: str | None
    timestamp: str


@dataclass
class ServiceHealth:
    """Aggregated health status for all services."""

    overall: str  # healthy, degraded, down
    checks: list[HealthCheckResult]
    timestamp: str


# Default endpoints to monitor
DEFAULT_ENDPOINTS: list[EndpointConfig] = [
    {
        "name": "API Prod",
        "url": "https://api.vibebrowser.app/health",
        "critical": True,
    },
    {
        "name": "API Dev",
        "url": "https://api-dev.vibebrowser.app/health",
        "critical": False,
    },
    {
        "name": "Portal",
        "url": "https://portal.vibebrowser.app",
        "critical": True,
    },
    {
        "name": "Docs",
        "url": "https://docs.vibebrowser.app",
        "critical": False,
    },
    {
        "name": "Langfuse",
        "url": "https://langfuse.vibebrowser.app/api/public/health",
        "critical": False,
    },
]


class HealthConnector:
    """
    Connector for monitoring service health.

    Features:
    - HTTP health checks
    - Latency monitoring
    - SSL certificate expiry checks
    - Aggregated health status
    """

    # Thresholds
    LATENCY_WARNING_MS = 1000  # 1 second
    LATENCY_CRITICAL_MS = 5000  # 5 seconds
    SSL_EXPIRY_WARNING_DAYS = 14

    def __init__(self, endpoints: list[EndpointConfig] | None = None):
        self.endpoints: list[EndpointConfig] = endpoints or DEFAULT_ENDPOINTS

    def check_endpoint(self, url: str, timeout: int = 10) -> HealthCheckResult:
        """Check a single endpoint."""
        timestamp = datetime.utcnow().isoformat() + "Z"

        try:
            start = datetime.utcnow()
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
            latency = (datetime.utcnow() - start).total_seconds() * 1000

            if resp.status_code == 200:
                status = "healthy"
            elif resp.status_code < 500:
                status = "degraded"
            else:
                status = "down"

            return HealthCheckResult(
                url=url,
                status=status,
                status_code=resp.status_code,
                latency_ms=round(latency, 2),
                error=None,
                timestamp=timestamp,
            )

        except requests.exceptions.Timeout:
            return HealthCheckResult(
                url=url,
                status="down",
                status_code=None,
                latency_ms=timeout * 1000,
                error="Timeout",
                timestamp=timestamp,
            )
        except requests.exceptions.ConnectionError as e:
            return HealthCheckResult(
                url=url,
                status="down",
                status_code=None,
                latency_ms=0,
                error=f"Connection error: {str(e)[:100]}",
                timestamp=timestamp,
            )
        except Exception as e:
            return HealthCheckResult(
                url=url,
                status="down",
                status_code=None,
                latency_ms=0,
                error=str(e)[:100],
                timestamp=timestamp,
            )

    def check_ssl_expiry(self, hostname: str) -> int | None:
        """Check SSL certificate expiry in days."""
        try:
            context = ssl.create_default_context()
            with (
                socket.create_connection((hostname, 443), timeout=10) as sock,
                context.wrap_socket(sock, server_hostname=hostname) as ssock,
            ):
                cert = ssock.getpeercert()
                if cert is None:
                    return None
                not_after = cert.get("notAfter")
                if not isinstance(not_after, str):
                    return None
                expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                days_left = (expiry - datetime.utcnow()).days
                return days_left
        except Exception as e:
            logger.warning(f"SSL check failed for {hostname}: {e}")
            return None

    def check_all(self) -> ServiceHealth:
        """Check all configured endpoints."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        checks = []
        critical_down = False
        any_degraded = False

        for endpoint in self.endpoints:
            result = self.check_endpoint(endpoint["url"])
            checks.append(result)

            if result.status == "down" and endpoint.get("critical", False):
                critical_down = True
            elif result.status in ("down", "degraded"):
                any_degraded = True

        # Determine overall status
        if critical_down:
            overall = "down"
        elif any_degraded:
            overall = "degraded"
        else:
            overall = "healthy"

        return ServiceHealth(
            overall=overall,
            checks=checks,
            timestamp=timestamp,
        )

    def get_alerts(self) -> list[dict]:
        """Get list of alerts for unhealthy services."""
        health = self.check_all()
        alerts = []

        for check in health.checks:
            endpoint = next(
                (e for e in self.endpoints if e["url"] == check.url),
                {"name": check.url, "critical": False},
            )

            # Down alert
            if check.status == "down":
                alerts.append(
                    {
                        "type": "service_down",
                        "severity": ("critical" if endpoint.get("critical") else "warning"),
                        "service": endpoint.get("name", check.url),
                        "message": f"{endpoint.get('name', check.url)} is DOWN: {check.error or 'No response'}",
                        "url": check.url,
                        "timestamp": check.timestamp,
                    }
                )

            # High latency alert
            elif check.latency_ms > self.LATENCY_CRITICAL_MS:
                alerts.append(
                    {
                        "type": "high_latency",
                        "severity": "critical",
                        "service": endpoint.get("name", check.url),
                        "message": f"{endpoint.get('name', check.url)} high latency: {check.latency_ms:.0f}ms",
                        "url": check.url,
                        "latency_ms": check.latency_ms,
                        "timestamp": check.timestamp,
                    }
                )
            elif check.latency_ms > self.LATENCY_WARNING_MS:
                alerts.append(
                    {
                        "type": "high_latency",
                        "severity": "warning",
                        "service": endpoint.get("name", check.url),
                        "message": f"{endpoint.get('name', check.url)} elevated latency: {check.latency_ms:.0f}ms",
                        "url": check.url,
                        "latency_ms": check.latency_ms,
                        "timestamp": check.timestamp,
                    }
                )

        # Check SSL expiry for critical endpoints
        for endpoint in self.endpoints:
            if endpoint.get("critical"):
                hostname = urlparse(endpoint["url"]).netloc
                days_left = self.check_ssl_expiry(hostname)
                if days_left is not None and days_left < self.SSL_EXPIRY_WARNING_DAYS:
                    alerts.append(
                        {
                            "type": "ssl_expiry",
                            "severity": "critical" if days_left < 7 else "warning",
                            "service": endpoint.get("name", hostname),
                            "message": f"SSL certificate expires in {days_left} days",
                            "hostname": hostname,
                            "days_left": days_left,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                    )

        return alerts

    def get_summary(self) -> dict:
        """Get health summary for reporting."""
        health = self.check_all()

        return {
            "overall": health.overall,
            "timestamp": health.timestamp,
            "services": [
                {
                    "url": c.url,
                    "status": c.status,
                    "status_code": c.status_code,
                    "latency_ms": c.latency_ms,
                    "error": c.error,
                }
                for c in health.checks
            ],
            "alerts": self.get_alerts(),
        }
