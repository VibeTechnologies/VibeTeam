"""
OpenCode agent implementations for VibeTeam.

Uses the OpenCode CLI (`opencode run`) for agent execution.
Supports session persistence via opencode's built-in session management.

Features:
- CLI-based execution (no server required)
- NDJSON response parsing
- Session persistence across conversations
- @mention-based handoffs between agents
"""

from agents.opencode.base import (
    OpenCodeAgentConfig,
    OpenCodeBaseAgent,
)
from agents.opencode.client import (
    OpenCodeClient,
    OpenCodeClientConfig,
    OpenCodeResponse,
    create_client,
)
from agents.opencode.marketing_manager import (
    OpenCodeMarketingManager,
    create_marketing_manager,
)
from agents.opencode.product_manager import (
    OpenCodeProductManager,
    create_product_manager,
)
from agents.opencode.release_engineer import (
    OpenCodeReleaseEngineer,
    create_release_engineer,
)
from agents.opencode.software_engineer import (
    OpenCodeSoftwareEngineer,
    create_software_engineer,
)
from agents.opencode.support_engineer import (
    OpenCodeSupportEngineer,
    create_support_engineer,
)
from agents.opencode.team import (
    OpenCodeTeam,
    TeamConfig,
    create_team,
)

__all__ = [
    # Client
    "OpenCodeClient",
    "OpenCodeClientConfig",
    "OpenCodeResponse",
    "create_client",
    # Base
    "OpenCodeAgentConfig",
    "OpenCodeBaseAgent",
    # Agents
    "OpenCodeMarketingManager",
    "OpenCodeProductManager",
    "OpenCodeReleaseEngineer",
    "OpenCodeSoftwareEngineer",
    "OpenCodeSupportEngineer",
    # Team
    "OpenCodeTeam",
    "TeamConfig",
    "create_team",
    # Factory functions
    "create_marketing_manager",
    "create_product_manager",
    "create_release_engineer",
    "create_software_engineer",
    "create_support_engineer",
]
