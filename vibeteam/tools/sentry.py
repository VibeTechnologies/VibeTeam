"""
Sentry Tool - OpenHands tool wrapper for Sentry connector.

Provides agent-callable functions for Sentry error tracking operations.
"""

import json
from dataclasses import asdict
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.sentry import SentryConnector


class SentryTool(BaseTool):
    """
    Tool for interacting with Sentry error tracking.

    Wraps the SentryConnector for use by VibeTeam agents.
    """

    name = "sentry"
    description = "Fetch and manage Sentry issues and errors"

    def __init__(self, auth_token: str | None = None, org: str = "vibetechnologies"):
        self.connector = SentryConnector(auth_token=auth_token, org=org)

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
                                "fetch_issues",
                                "get_issue_details",
                                "add_comment",
                                "resolve_issue",
                                "ignore_issue",
                                "get_project_stats",
                            ],
                            "description": "The Sentry action to perform",
                        },
                        "issue_id": {
                            "type": "string",
                            "description": "Sentry issue ID",
                        },
                        "project": {
                            "type": "string",
                            "description": "Project name (optional, defaults to all)",
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Time window in hours (default: 24)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return",
                        },
                        "text": {
                            "type": "string",
                            "description": "Comment text",
                        },
                        "resolution": {
                            "type": "string",
                            "enum": ["resolved", "ignored", "unresolved"],
                            "description": "Resolution status",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Sentry action."""
        action = kwargs.get("action")

        try:
            if action == "fetch_issues":
                project = kwargs.get("project")
                hours = kwargs.get("hours", 24)
                limit = kwargs.get("limit", 25)
                issues = self.connector.fetch_unresolved_issues(
                    project=project, hours=hours, limit=limit
                )
                output = json.dumps([asdict(i) for i in issues], indent=2)
                return ToolResult(
                    success=True,
                    output=output,
                    metadata={"count": len(issues)},
                )

            elif action == "get_issue_details":
                issue_id = kwargs.get("issue_id")
                if not issue_id:
                    return ToolResult(success=False, output="", error="issue_id required")
                details = self.connector.get_issue_details(issue_id)
                return ToolResult(success=True, output=json.dumps(details, indent=2))

            elif action == "add_comment":
                issue_id = kwargs.get("issue_id")
                text = kwargs.get("text")
                if not issue_id or not text:
                    return ToolResult(success=False, output="", error="issue_id and text required")
                self.connector.add_comment(issue_id, text)
                return ToolResult(success=True, output=f"Comment added to issue {issue_id}")

            elif action == "resolve_issue":
                issue_id = kwargs.get("issue_id")
                resolution = kwargs.get("resolution", "resolved")
                if not issue_id:
                    return ToolResult(success=False, output="", error="issue_id required")
                self.connector.resolve_issue(issue_id, resolution)
                return ToolResult(success=True, output=f"Issue {issue_id} marked as {resolution}")

            elif action == "ignore_issue":
                issue_id = kwargs.get("issue_id")
                if not issue_id:
                    return ToolResult(success=False, output="", error="issue_id required")
                self.connector.ignore_issue(issue_id)
                return ToolResult(success=True, output=f"Issue {issue_id} ignored")

            elif action == "get_project_stats":
                project = kwargs.get("project", "vibebrowserextension")
                hours = kwargs.get("hours", 24)
                stats = self.connector.get_project_stats(project, hours)
                return ToolResult(success=True, output=json.dumps(stats, indent=2))

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
