"""
OpenCode team orchestration for VibeTeam.

Manages the 5-agent team with @mention-based handoffs.
"""

from dataclasses import dataclass
from typing import Any

from agents.opencode.base import OpenCodeAgentConfig
from agents.opencode.marketing_manager import (
    create_marketing_manager,
)
from agents.opencode.product_manager import (
    create_product_manager,
)
from agents.opencode.release_engineer import (
    create_release_engineer,
)
from agents.opencode.software_engineer import (
    create_software_engineer,
)
from agents.opencode.support_engineer import (
    create_support_engineer,
)

# Agent role to @mention mapping
ROLE_MENTIONS = {
    "software_engineer": ["@swe", "@alan", "@software"],
    "release_engineer": ["@release", "@einstein", "@deploy"],
    "support_engineer": ["@support", "@grace", "@help"],
    "product_manager": ["@pm", "@maya", "@product"],
    "marketing_manager": ["@marketer", "@ada", "@marketing"],
}


@dataclass
class TeamConfig:
    """Configuration for the OpenCode team."""

    agent_config: OpenCodeAgentConfig | None = None
    timeout: int = 120


class OpenCodeTeam:
    """
    Team orchestration for OpenCode-based agents.

    Implements the routing logic:
    - IF @AgentName mentioned → Route DIRECTLY to that agent
    - ELSE → BROADCAST to ALL agents, each decides if they claim

    Example usage:
        team = OpenCodeTeam()
        response = team.route("@swe Fix the login bug")
        # Routes directly to SoftwareEngineer

        response = team.route("We need to ship v2.0")
        # Broadcasts to all agents, each evaluates if they should respond
    """

    def __init__(self, config: TeamConfig | None = None):
        self.config = config or TeamConfig()

        # Create all agents
        self.agents = {
            "software_engineer": create_software_engineer(self.config.agent_config),
            "release_engineer": create_release_engineer(self.config.agent_config),
            "support_engineer": create_support_engineer(self.config.agent_config),
            "product_manager": create_product_manager(self.config.agent_config),
            "marketing_manager": create_marketing_manager(self.config.agent_config),
        }

    def _detect_mentioned_agents(self, message: str) -> list[str]:
        """
        Detect which agents are @mentioned in the message.

        Returns list of role names that were mentioned.
        """
        message_lower = message.lower()
        mentioned = []

        for role, mentions in ROLE_MENTIONS.items():
            for mention in mentions:
                if mention in message_lower:
                    if role not in mentioned:
                        mentioned.append(role)
                    break

        return mentioned

    def route(
        self,
        message: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Route a message to the appropriate agent(s).

        If @mentions are detected, routes directly to those agents.
        Otherwise, broadcasts to all agents for evaluation.

        Args:
            message: The incoming message
            context_type: Type of context (slack, discord, ephemeral)
            context_id: ID for session persistence

        Returns:
            dict with responses from agents that handled the message
        """
        mentioned = self._detect_mentioned_agents(message)

        if mentioned:
            # Direct routing to mentioned agents
            return self._route_direct(message, mentioned, context_type, context_id)
        else:
            # Broadcast to all agents
            return self._route_broadcast(message, context_type, context_id)

    def _route_direct(
        self,
        message: str,
        roles: list[str],
        context_type: str,
        context_id: str | None,
    ) -> dict[str, Any]:
        """Route message directly to specific agents."""
        responses = {}

        for role in roles:
            agent = self.agents.get(role)
            if agent:
                try:
                    result = agent.run(
                        task=message,
                        context_type=context_type,
                        context_id=context_id,
                    )
                    responses[role] = result
                except Exception as e:
                    responses[role] = {
                        "response": f"Error: {e}",
                        "error": True,
                    }

        return {
            "routing": "direct",
            "mentioned": roles,
            "responses": responses,
        }

    def _route_broadcast(
        self,
        message: str,
        context_type: str,
        context_id: str | None,
    ) -> dict[str, Any]:
        """
        Broadcast message to all agents.

        Each agent evaluates if they should handle the task.
        In this implementation, we ask the ProductManager to coordinate.
        """
        # For broadcasts, PM acts as coordinator
        pm = self.agents["product_manager"]

        coordination_prompt = f"""You are coordinating a team task.
The following message was received and needs to be assigned:

MESSAGE: {message}

Based on this message, determine:
1. Which team member(s) should handle this? (Options: @swe, @release, @support, @marketer, or yourself)
2. Provide the task assignment with clear instructions.

If this is a product/strategy question, handle it yourself.
Otherwise, delegate using @mentions."""

        try:
            result = pm.run(
                task=coordination_prompt,
                context_type=context_type,
                context_id=context_id,
            )

            # Check if PM delegated to others
            pm_response = result.get("response", "")
            delegated_to = self._detect_mentioned_agents(pm_response)

            if delegated_to:
                # PM delegated - route to those agents
                follow_up = self._route_direct(
                    message=f"Task from PM: {message}\n\nPM's context: {pm_response}",
                    roles=delegated_to,
                    context_type=context_type,
                    context_id=context_id,
                )
                return {
                    "routing": "broadcast-delegated",
                    "coordinator": "product_manager",
                    "coordinator_response": result,
                    "delegated_to": delegated_to,
                    "delegate_responses": follow_up.get("responses", {}),
                }
            else:
                # PM handled it directly
                return {
                    "routing": "broadcast-handled",
                    "coordinator": "product_manager",
                    "responses": {"product_manager": result},
                }

        except Exception as e:
            return {
                "routing": "broadcast-error",
                "error": str(e),
            }

    async def route_async(
        self,
        message: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of route."""
        import asyncio

        mentioned = self._detect_mentioned_agents(message)

        if mentioned:
            # Direct routing - run mentioned agents in parallel
            tasks = []
            for role in mentioned:
                agent = self.agents.get(role)
                if agent:
                    tasks.append((role, agent.run_async(message, context_type, context_id)))

            responses = {}
            for role, task in tasks:
                try:
                    result = await task
                    responses[role] = result
                except Exception as e:
                    responses[role] = {"response": f"Error: {e}", "error": True}

            return {
                "routing": "direct",
                "mentioned": mentioned,
                "responses": responses,
            }
        else:
            # For broadcast, use sync version in thread
            return await asyncio.to_thread(self._route_broadcast, message, context_type, context_id)


def create_team(config: TeamConfig | None = None) -> OpenCodeTeam:
    """Factory function to create OpenCode team."""
    return OpenCodeTeam(config)
