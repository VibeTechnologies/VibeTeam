"""
GitHub Tool - OpenHands tool wrapper for GitHub connector.

Provides agent-callable functions for GitHub operations.
"""

import json
from dataclasses import asdict
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.github import GitHubConnector


class GitHubTool(BaseTool):
    """
    Tool for interacting with GitHub issues and pull requests.

    Wraps the GitHubConnector for use by VibeTeam agents.
    """

    name = "github"
    description = "Manage GitHub issues and pull requests"

    def __init__(
        self,
        token: str | None = None,
        owner: str = "VibeTechnologies",
        repo: str = "VibeWebAgent",
    ):
        self.connector = GitHubConnector(token=token, owner=owner, repo=repo)

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
                                "get_issue",
                                "update_issue",
                                "add_comment",
                                "search_issues",
                                "get_customer_requests",
                                "add_customer_request",
                                "get_pr",
                                "list_prs",
                                "create_review",
                            ],
                            "description": "The GitHub action to perform",
                        },
                        "issue_number": {
                            "type": "integer",
                            "description": "Issue or PR number",
                        },
                        "pr_number": {
                            "type": "integer",
                            "description": "Pull request number",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "body": {
                            "type": "string",
                            "description": "Comment or update body",
                        },
                        "title": {
                            "type": "string",
                            "description": "Issue or PR title",
                        },
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "description": "Issue/PR state filter",
                        },
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Issue labels",
                        },
                        "request": {
                            "type": "string",
                            "description": "Customer request description",
                        },
                        "source": {
                            "type": "string",
                            "description": "Request source (email, docs-chat, etc.)",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["P0", "P1", "P2", "P3"],
                            "description": "Request priority",
                        },
                        "analysis": {
                            "type": "string",
                            "description": "PM analysis notes",
                        },
                        "event": {
                            "type": "string",
                            "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"],
                            "description": "Review event type",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a GitHub action."""
        action = kwargs.get("action")

        try:
            if action == "get_issue":
                issue_number = kwargs.get("issue_number")
                if not issue_number:
                    return ToolResult(
                        success=False, output="", error="issue_number required"
                    )
                issue = self.connector.get_issue(issue_number)
                return ToolResult(
                    success=True, output=json.dumps(asdict(issue), indent=2)
                )

            elif action == "update_issue":
                issue_number = kwargs.get("issue_number")
                if not issue_number:
                    return ToolResult(
                        success=False, output="", error="issue_number required"
                    )
                issue = self.connector.update_issue(
                    issue_number,
                    title=kwargs.get("title"),
                    body=kwargs.get("body"),
                    state=kwargs.get("state"),
                    labels=kwargs.get("labels"),
                )
                return ToolResult(success=True, output=f"Updated issue #{issue.number}")

            elif action == "add_comment":
                issue_number = kwargs.get("issue_number")
                body = kwargs.get("body")
                if not issue_number or not body:
                    return ToolResult(
                        success=False, output="", error="issue_number and body required"
                    )
                self.connector.add_issue_comment(issue_number, body)
                return ToolResult(
                    success=True, output=f"Comment added to issue #{issue_number}"
                )

            elif action == "search_issues":
                query = kwargs.get("query", "")
                state = kwargs.get("state", "open")
                labels = kwargs.get("labels")
                limit = kwargs.get("limit", 10)
                issues = self.connector.search_issues(query, state, labels, limit)
                output = json.dumps([asdict(i) for i in issues], indent=2)
                return ToolResult(success=True, output=output)

            elif action == "get_customer_requests":
                body, requests = self.connector.get_customer_requests_table()
                return ToolResult(success=True, output=json.dumps(requests, indent=2))

            elif action == "add_customer_request":
                request = kwargs.get("request")
                source = kwargs.get("source", "unknown")
                priority = kwargs.get("priority", "P2")
                analysis = kwargs.get("analysis", "")
                if not request:
                    return ToolResult(
                        success=False, output="", error="request required"
                    )
                self.connector.add_customer_request(
                    request=request,
                    source=source,
                    priority=priority,
                    analysis=analysis,
                )
                return ToolResult(success=True, output="Customer request added")

            elif action == "get_pr":
                pr_number = kwargs.get("pr_number")
                if not pr_number:
                    return ToolResult(
                        success=False, output="", error="pr_number required"
                    )
                pr = self.connector.get_pr(pr_number)
                return ToolResult(success=True, output=json.dumps(asdict(pr), indent=2))

            elif action == "list_prs":
                state = kwargs.get("state", "open")
                limit = kwargs.get("limit", 10)
                prs = self.connector.list_prs(state=state, limit=limit)
                output = json.dumps([asdict(p) for p in prs], indent=2)
                return ToolResult(success=True, output=output)

            elif action == "create_review":
                pr_number = kwargs.get("pr_number")
                body = kwargs.get("body")
                event = kwargs.get("event", "COMMENT")
                if not pr_number or not body:
                    return ToolResult(
                        success=False, output="", error="pr_number and body required"
                    )
                self.connector.create_review(pr_number, body, event)
                return ToolResult(
                    success=True, output=f"Review added to PR #{pr_number}"
                )

            else:
                return ToolResult(
                    success=False, output="", error=f"Unknown action: {action}"
                )

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
