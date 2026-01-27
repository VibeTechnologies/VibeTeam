"""
OpenHands team orchestration for VibeTeam.

Coordinates multiple agents and routes tasks based on @mentions.
"""

from typing import Any

from agents.config import AgentConfig
from agents.openhands.release_engineer import OpenHandsReleaseEngineer
from agents.openhands.marketing_manager import OpenHandsMarketingManager
from agents.openhands.support_engineer import OpenHandsSupportEngineer


class OpenHandsTeam:
    """
    Team orchestration for OpenHands agents.

    Routes tasks to appropriate agents based on @mentions or keywords.
    Manages agent lifecycle and session context.
    """

    def __init__(self, config: AgentConfig | None = None):
        self.config = config
        self._agents: dict[str, Any] = {}

    def _get_agent(self, role: str) -> Any:
        """Lazy-load agents on demand."""
        if role not in self._agents:
            if role == "release_engineer":
                self._agents[role] = OpenHandsReleaseEngineer(self.config)
            elif role == "marketing_manager":
                self._agents[role] = OpenHandsMarketingManager(self.config)
            elif role == "support_engineer":
                self._agents[role] = OpenHandsSupportEngineer(self.config)
            else:
                raise ValueError(f"Unknown agent role: {role}")
        return self._agents[role]

    def parse_mention(self, text: str) -> str | None:
        """
        Parse @mention from text to determine target agent.

        Supported mentions:
        - @ReleaseEngineer, @release, @einstein
        - @MarketingManager, @marketing, @ada
        - @SupportEngineer, @support, @grace
        """
        text_lower = text.lower()

        release_patterns = ["@releaseengineer", "@release", "@einstein"]
        marketing_patterns = ["@marketingmanager", "@marketing", "@ada"]
        support_patterns = ["@supportengineer", "@support", "@grace"]

        for pattern in release_patterns:
            if pattern in text_lower:
                return "release_engineer"

        for pattern in marketing_patterns:
            if pattern in text_lower:
                return "marketing_manager"

        for pattern in support_patterns:
            if pattern in text_lower:
                return "support_engineer"

        return None

    def route_by_keywords(self, text: str) -> str:
        """
        Route to agent based on keywords if no @mention found.
        """
        text_lower = text.lower()

        # Release Engineer keywords
        if any(
            kw in text_lower
            for kw in [
                "deploy",
                "release",
                "k8s",
                "kubernetes",
                "pipeline",
                "ci/cd",
                "build",
                "version",
                "tag",
                "infrastructure",
            ]
        ):
            return "release_engineer"

        # Marketing Manager keywords
        if any(
            kw in text_lower
            for kw in [
                "post",
                "tweet",
                "linkedin",
                "social",
                "blog",
                "announcement",
                "marketing",
                "content",
                "brand",
            ]
        ):
            return "marketing_manager"

        # Support Engineer keywords
        if any(
            kw in text_lower
            for kw in [
                "email",
                "customer",
                "support",
                "ticket",
                "calendar",
                "meeting",
                "sentry",
                "error",
                "langfuse",
                "schedule",
            ]
        ):
            return "support_engineer"

        # Default to support engineer
        return "support_engineer"

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """
        Route and execute task with appropriate agent.

        Args:
            task: The task description (may contain @mentions)
            context_type: Type of context (issue, pr, slack, etc.)
            context_id: ID for the context
            workspace: Working directory

        Returns:
            dict with response, agent used, and metadata
        """
        # Determine target agent
        role = self.parse_mention(task)
        if role is None:
            role = self.route_by_keywords(task)

        # Get and run agent
        agent = self._get_agent(role)
        result = agent.run(
            task=task,
            context_type=context_type,
            context_id=context_id,
            workspace=workspace,
        )

        return result

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, workspace)


def create_team(config: AgentConfig | None = None) -> OpenHandsTeam:
    """Factory function to create OpenHands team."""
    return OpenHandsTeam(config)
