"""
Base Role - Foundation for all VibeTeam roles, extending MetaGPT Role.
"""

from typing import Any

from metagpt.roles import Role
from metagpt.schema import Message
from pydantic import Field


class VibeRole(Role):
    """
    Base class for all VibeTeam roles.

    Extends MetaGPT Role with:
    - GitHub Copilot subscription compatibility (uses litellm)
    - Standardized action patterns
    - Team communication protocols
    """

    name: str = Field(default="VibeRole")
    profile: str = Field(default="Team Member")
    goal: str = Field(default="Contribute to team success")
    constraints: str = Field(default="Follow team protocols and best practices")

    # Model configuration - uses Azure OpenAI gpt-5.2 for high-quality agent reasoning
    model: str = Field(default="azure/gpt-5.2")
    temperature: float = Field(default=0.3)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    async def _think(self) -> bool:
        """Determine the next action to take."""
        return await super()._think()

    async def _act(self) -> Message:
        """Execute the determined action."""
        return await super()._act()

    async def _observe(self) -> int:
        """Observe new messages from environment."""
        return await super()._observe()

    async def _react(self) -> Message:
        """React to observations by thinking and acting."""
        return await super()._react()
