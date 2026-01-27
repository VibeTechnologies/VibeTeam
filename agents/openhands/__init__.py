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

from agents.openhands.marketing_manager import (
    OpenHandsMarketingManager,
    create_marketing_manager,
)
from agents.openhands.product_manager import (
    OpenHandsProductManager,
    create_product_manager,
)
from agents.openhands.release_engineer import (
    OpenHandsReleaseEngineer,
    create_release_engineer,
)
from agents.openhands.software_engineer import (
    OpenHandsSoftwareEngineer,
    create_software_engineer,
)
from agents.openhands.support_engineer import (
    OpenHandsSupportEngineer,
    create_support_engineer,
)

__all__ = [
    "OpenHandsMarketingManager",
    "OpenHandsProductManager",
    "OpenHandsReleaseEngineer",
    "OpenHandsSoftwareEngineer",
    "OpenHandsSupportEngineer",
    "create_marketing_manager",
    "create_product_manager",
    "create_release_engineer",
    "create_software_engineer",
    "create_support_engineer",
]
