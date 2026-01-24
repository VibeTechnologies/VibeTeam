"""
Webhook handlers for VibeTeam.

This module provides webhook receivers for external services.
"""

from vibeteam.webhooks.server import app, create_app

__all__ = ["app", "create_app"]
