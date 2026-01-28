"""
AutoGen agent implementations for VibeTeam.

Uses AutoGen 0.4+ with:
- AssistantAgent for AI agents with tools
- SelectorGroupChat for dynamic speaker selection
- AzureOpenAIChatCompletionClient for Azure OpenAI
"""

from agents.autogen.marketing_manager import (
    AutoGenMarketingManager,
    create_marketing_manager,
)
from agents.autogen.product_manager import (
    AutoGenProductManager,
    create_product_manager,
)
from agents.autogen.release_engineer import (
    AutoGenReleaseEngineer,
    create_release_engineer,
)
from agents.autogen.software_engineer import (
    AutoGenSoftwareEngineer,
    create_software_engineer,
)
from agents.autogen.support_engineer import (
    AutoGenSupportEngineer,
    create_support_engineer,
)
from agents.autogen.team import AutoGenTeam, create_team

__all__ = [
    "AutoGenProductManager",
    "AutoGenReleaseEngineer",
    "AutoGenMarketingManager",
    "AutoGenSoftwareEngineer",
    "AutoGenSupportEngineer",
    "AutoGenTeam",
    "create_product_manager",
    "create_release_engineer",
    "create_marketing_manager",
    "create_software_engineer",
    "create_support_engineer",
    "create_team",
]
