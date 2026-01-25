"""
Health Check Tool - OpenHands tool wrapper for Health connector.

Provides agent-callable functions for service health monitoring.
"""

import json
from dataclasses import asdict
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.health import HealthConnector, EndpointConfig


class HealthCheckTool(BaseTool):
    """
    Tool for monitoring service health.

    Wraps the HealthConnector for use by VibeTeam agents.
    """

    name = "health_check"
    description = "Check health status of services and endpoints"

    def __init__(self, endpoints: list[EndpointConfig] | None = None):
        self.connector = HealthConnector(endpoints=endpoints)

    def get_schema(self) -> dict:
        """Return OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "check_endpoint",
                                "check_all",
                                "get_alerts",
                                "get_summary",
                                "check_ssl",
                            ],
                            "description": "The health check action to perform",
                        },
                        "url": {
                            "type": "string",
                            "description": "URL to check (for check_endpoint)",
                        },
                        "hostname": {
                            "type": "string",
                            "description": "Hostname for SSL check",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Request timeout in seconds (default: 10)",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a health check action."""
        action = kwargs.get("action")

        try:
            if action == "check_endpoint":
                url = kwargs.get("url")
                if not url:
                    return ToolResult(success=False, output="", error="url required")
                timeout = kwargs.get("timeout", 10)
                result = self.connector.check_endpoint(url, timeout)
                return ToolResult(
                    success=True,
                    output=json.dumps(asdict(result), indent=2),
                    metadata={"status": result.status},
                )

            elif action == "check_all":
                health = self.connector.check_all()
                output = {
                    "overall": health.overall,
                    "timestamp": health.timestamp,
                    "checks": [asdict(c) for c in health.checks],
                }
                return ToolResult(
                    success=True,
                    output=json.dumps(output, indent=2),
                    metadata={"overall": health.overall},
                )

            elif action == "get_alerts":
                alerts = self.connector.get_alerts()
                return ToolResult(
                    success=True,
                    output=json.dumps(alerts, indent=2),
                    metadata={"count": len(alerts)},
                )

            elif action == "get_summary":
                summary = self.connector.get_summary()
                return ToolResult(
                    success=True,
                    output=json.dumps(summary, indent=2),
                    metadata={"overall": summary.get("overall")},
                )

            elif action == "check_ssl":
                hostname = kwargs.get("hostname")
                if not hostname:
                    return ToolResult(success=False, output="", error="hostname required")
                days_left = self.connector.check_ssl_expiry(hostname)
                if days_left is None:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Could not check SSL for {hostname}",
                    )
                return ToolResult(
                    success=True,
                    output=f"SSL certificate for {hostname} expires in {days_left} days",
                    metadata={"days_left": days_left},
                )

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
