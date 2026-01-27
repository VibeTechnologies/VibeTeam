"""
OpenHands agent implementations for VibeTeam.

OpenHands SDK provides:
- Built-in session persistence via Conversation
- First-class MCP support
- Type-safe tool system
- Docker sandbox for code execution

Note: OpenHands integration is currently blocked due to Azure OpenAI compatibility.
"""

from agents.openhands.release_engineer import (
    OpenHandsReleaseEngineer,
    create_release_engineer,
)

__all__ = ["OpenHandsReleaseEngineer", "create_release_engineer"]
