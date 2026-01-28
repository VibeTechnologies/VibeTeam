"""
VibeTeam Gateway - Routes external events to agent microservices.

This module provides a FastAPI gateway that handles:
- GitHub webhooks (issues.assigned, issue_comment)
- Slack events (app_mention, message.im)
- Sentry webhooks (issue.created)
- REST API for manual task invocation

Instead of running agents as subprocesses, it routes requests to
the agent microservices (autogen-svc, crewai-svc) via HTTP.
"""

from vibeteam.gateway.server import app

__all__ = ["app"]
