"""
Multi-framework agent implementations for VibeTeam.

This package contains implementations of the same agents across three frameworks:
- OpenHands: Built-in sessions, MCP native, 77.6% SWE-Bench
- CrewAI: Multi-agent orchestration, 40+ built-in tools
- AutoGen: Conversational agents, group chat patterns

Each framework implements:
- ReleaseEngineer: Shell, file editing, k3s deployment
- MarketingManager: Chrome DevTools, social media
- SupportEngineer: Gmail, GCalendar, Langfuse, Sentry
"""

from enum import Enum


class AgentFramework(Enum):
    """Supported agent frameworks."""

    OPENHANDS = "openhands"
    CREWAI = "crewai"
    AUTOGEN = "autogen"


class AgentRole(Enum):
    """Agent roles in VibeTeam."""

    RELEASE_ENGINEER = "release_engineer"
    MARKETING_MANAGER = "marketing_manager"
    SUPPORT_ENGINEER = "support_engineer"
