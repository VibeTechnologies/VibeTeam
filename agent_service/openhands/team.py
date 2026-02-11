from __future__ import annotations

"""
OpenHands team orchestration for VibeTeam.

Coordinates multiple agents and routes tasks based on @mentions.
"""

from typing import Any

from agents.config import AgentConfig
from .marketing_manager import OpenHandsMarketingManager
from .product_manager import OpenHandsProductManager
from .release_engineer import OpenHandsReleaseEngineer
from .software_engineer import OpenHandsSoftwareEngineer
from .support_engineer import OpenHandsSupportEngineer
from agents.shared.role_resolver import parse_first_role_mention, route_by_keywords


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
        """Lazy-load agents on demand.

        Each agent constructor accepts an optional AgentConfig.  Passing None
        lets the agent fall back to its own role-specific default config
        (e.g. MARKETING_MANAGER_CONFIG) which carries the correct MCP
        servers.  A generic AgentConfig() would override those defaults
        with an empty mcp_servers dict, breaking agents that rely on MCP.
        """
        if role not in self._agents:
            if role == "release_engineer":
                self._agents[role] = OpenHandsReleaseEngineer()
            elif role == "marketing_manager":
                self._agents[role] = OpenHandsMarketingManager()
            elif role == "support_engineer":
                self._agents[role] = OpenHandsSupportEngineer()
            elif role == "product_manager":
                self._agents[role] = OpenHandsProductManager()
            elif role == "software_engineer":
                self._agents[role] = OpenHandsSoftwareEngineer()
            else:
                raise ValueError(f"Unknown agent role: {role}")
        return self._agents[role]

    def parse_mention(self, text: str) -> str | None:
        """
        Parse @mention from text to determine target agent.

        Delegates to agents.shared.role_resolver.parse_first_role_mention
        which supports all mention patterns: @RoleName, /RoleName,
        persona names (@einstein, @grace, @ada), and short aliases
        (@swe, @pm, @dev, etc.).
        """
        return parse_first_role_mention(text)

    def route_by_keywords(self, text: str) -> str:
        """
        Route to agent based on keywords if no @mention found.

        Delegates to agents.shared.role_resolver.route_by_keywords
        which is the single source of truth for keyword routing.
        """
        return route_by_keywords(text)

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
