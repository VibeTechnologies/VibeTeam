"""Route handlers for the gateway."""

from vibeteam.gateway.routes.api import router as api_router
from vibeteam.gateway.routes.github import router as github_router
from vibeteam.gateway.routes.sentry import router as sentry_router
from vibeteam.gateway.routes.slack import router as slack_router

__all__ = ["github_router", "slack_router", "sentry_router", "api_router"]
