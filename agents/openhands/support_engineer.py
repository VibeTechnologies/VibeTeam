"""
SupportEngineer agent using OpenHands.

Capabilities:
- Gmail access via MCP for email management
- Google Calendar via MCP for scheduling
- Langfuse integration for LLM observability
- Sentry integration for error tracking

Note: OpenHands integration is currently blocked due to Azure OpenAI compatibility issues.
"""

from typing import Any

from agents.config import SUPPORT_ENGINEER_CONFIG, AgentConfig

try:
    from openhands.sdk import LLM, Agent, Conversation

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False


SUPPORT_ENGINEER_SYSTEM_PROMPT = """You are Grace, the Support Engineer for VibeTeam.

Your responsibilities:
1. **Email Support**: Read, triage, and respond to customer emails
2. **Scheduling**: Manage calendar events and meeting requests
3. **Issue Tracking**: Monitor Sentry for errors and create GitHub issues
4. **LLM Observability**: Review Langfuse traces for quality issues

When you complete a task, summarize what was done and any next steps.
"""


class OpenHandsSupportEngineer:
    """
    Support Engineer agent using OpenHands SDK.

    Note: Currently blocked due to Azure OpenAI compatibility issues.
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or SUPPORT_ENGINEER_CONFIG
        self._LLM = LLM
        self._Agent = Agent
        self._Conversation = Conversation

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Run a task with the Support Engineer agent.

        Raises:
            NotImplementedError: OpenHands Azure integration is blocked
        """
        _ = (task, context_type, context_id)

        raise NotImplementedError(
            "OpenHands integration is currently blocked due to Azure OpenAI compatibility. "
            "Use AutoGen agents instead."
        )

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Async version of run."""
        return self.run(task, context_type, context_id)


def create_support_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsSupportEngineer:
    """Factory function to create Support Engineer agent."""
    return OpenHandsSupportEngineer(config)
