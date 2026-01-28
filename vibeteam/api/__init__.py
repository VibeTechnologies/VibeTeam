"""
VibeTeam API - FastAPI endpoints for the Supervisor Agent.

Provides a chat interface for interacting with the VibeTeam through
the Supervisor Agent with Swarm orchestration.
"""

from vibeteam.api.main import app, chat, get_session_history, health

__all__ = [
    "app",
    "chat",
    "health",
    "get_session_history",
]
