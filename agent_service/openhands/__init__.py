"""
OpenHands agent implementations for VibeTeam.

OpenHands SDK v1.2.1 provides:
- Built-in session persistence via LocalConversation
- First-class MCP support
- Type-safe tool system
- Docker sandbox for code execution

Azure OpenAI Configuration:
- Use model format: azure/<deployment-name>
- Set max_output_tokens=4096 (default exceeds Azure limits)
"""

from agent_service.config import AgentConfig

from .agent import Agent, create_agent
from .team import OpenHandsTeam, create_team

OpenHandsAgent = Agent


def OpenHandsSoftwareEngineer(config: AgentConfig | None = None) -> Agent:
    return create_agent("software_engineer", config=config)


def OpenHandsSupportEngineer(config: AgentConfig | None = None) -> Agent:
    return create_agent("support_engineer", config=config)


def OpenHandsReleaseEngineer(config: AgentConfig | None = None) -> Agent:
    return create_agent("release_engineer", config=config)


def OpenHandsProductManager(config: AgentConfig | None = None) -> Agent:
    return create_agent("product_manager", config=config)


def OpenHandsMarketingManager(config: AgentConfig | None = None) -> Agent:
    return create_agent("marketing_manager", config=config)


create_software_engineer = OpenHandsSoftwareEngineer
create_support_engineer = OpenHandsSupportEngineer
create_release_engineer = OpenHandsReleaseEngineer
create_product_manager = OpenHandsProductManager
create_marketing_manager = OpenHandsMarketingManager

__all__ = [
    "Agent",
    "OpenHandsAgent",
    "OpenHandsMarketingManager",
    "OpenHandsProductManager",
    "OpenHandsReleaseEngineer",
    "OpenHandsSoftwareEngineer",
    "OpenHandsSupportEngineer",
    "OpenHandsTeam",
    "create_agent",
    "create_marketing_manager",
    "create_product_manager",
    "create_release_engineer",
    "create_software_engineer",
    "create_support_engineer",
    "create_team",
]
