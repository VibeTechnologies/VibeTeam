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

from .agent import Agent
from .marketing_manager import (
    OpenHandsMarketingManager,
    create_marketing_manager,
)
from .product_manager import (
    OpenHandsProductManager,
    create_product_manager,
)
from .release_engineer import (
    OpenHandsReleaseEngineer,
    create_release_engineer,
)
from .software_engineer import (
    OpenHandsSoftwareEngineer,
    create_software_engineer,
)
from .support_engineer import (
    OpenHandsSupportEngineer,
    create_support_engineer,
)
from .team import OpenHandsTeam, create_team

__all__ = [
    "Agent",
    "OpenHandsMarketingManager",
    "OpenHandsProductManager",
    "OpenHandsReleaseEngineer",
    "OpenHandsSoftwareEngineer",
    "OpenHandsSupportEngineer",
    "OpenHandsTeam",
    "create_marketing_manager",
    "create_product_manager",
    "create_release_engineer",
    "create_software_engineer",
    "create_support_engineer",
    "create_team",
]
