"""
Langfuse Tool - OpenHands tool wrapper for Langfuse connector.

Provides agent-callable functions for LLM observability and anomaly detection.
"""

import json
from dataclasses import asdict
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.langfuse import LangfuseConnector


class LangfuseTool(BaseTool):
    """
    Tool for interacting with Langfuse observability.

    Wraps the LangfuseConnector for use by VibeTeam agents.
    """

    name = "langfuse"
    description = "Monitor LLM traces, detect anomalies, and track costs"

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
    ):
        self.connector = LangfuseConnector(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
        )

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
                                "get_traces",
                                "get_stats",
                                "detect_anomalies",
                                "get_daily_summary",
                                "health_check",
                            ],
                            "description": "The Langfuse action to perform",
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Time window in hours (default: 1)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum traces to return",
                        },
                        "name": {
                            "type": "string",
                            "description": "Filter traces by name",
                        },
                        "daily_token_budget": {
                            "type": "integer",
                            "description": "Daily token budget for anomaly detection",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Langfuse action."""
        action = kwargs.get("action")

        try:
            if action == "get_traces":
                hours = kwargs.get("hours", 1)
                limit = kwargs.get("limit", 100)
                name = kwargs.get("name")
                traces = self.connector.get_traces(hours=hours, limit=limit, name=name)
                return ToolResult(
                    success=True,
                    output=json.dumps(traces, indent=2, default=str),
                    metadata={"count": len(traces)},
                )

            elif action == "get_stats":
                hours = kwargs.get("hours", 1)
                stats = self.connector.get_stats(hours=hours)
                return ToolResult(
                    success=True,
                    output=json.dumps(asdict(stats), indent=2),
                )

            elif action == "detect_anomalies":
                hours = kwargs.get("hours", 1)
                budget = kwargs.get("daily_token_budget", 1_000_000)
                anomalies = self.connector.detect_anomalies(
                    hours=hours, daily_token_budget=budget
                )
                output = json.dumps([asdict(a) for a in anomalies], indent=2)
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"count": len(anomalies)},
                )

            elif action == "get_daily_summary":
                summary = self.connector.get_daily_summary()
                return ToolResult(success=True, output=json.dumps(summary, indent=2))

            elif action == "health_check":
                healthy = self.connector.health_check()
                return ToolResult(
                    success=True,
                    output=(
                        "Langfuse is healthy"
                        if healthy
                        else "Langfuse is not responding"
                    ),
                    metadata={"healthy": healthy},
                )

            else:
                return ToolResult(
                    success=False, output="", error=f"Unknown action: {action}"
                )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
