"""
VibeTeam - Autonomous AI team for SaaS development.

This package provides a multi-agent system with specialized roles:
- ProductManager: Defines requirements, roadmap, user stories
- SoftwareEngineer: Implements features, fixes bugs, writes tests
- Marketer: Creates content, social media posts, announcements
- SupportEngineer: Handles user issues, error investigation, documentation
- ReleaseEngineer: Manages deployments, versioning, releases, infrastructure

Usage:
    from vibeteam import VibeTeam, AgentType

    team = VibeTeam()
    result = await team.run("Implement GitHub issue #123")

    # Or use specific agent:
    result = await team.run("Create release notes", agent_type=AgentType.RELEASE)
"""

import logging
import os

__version__ = "3.0.0"

logger = logging.getLogger(__name__)


def _init_langfuse() -> bool:
    """
    Initialize Langfuse integration for LLM observability.

    Uses litellm's built-in Langfuse OTEL callback for automatic tracing.
    Returns True if initialized successfully, False otherwise.
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        logger.debug("Langfuse not configured (LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set)")
        return False

    # Set base URL if not already set
    if not os.environ.get("LANGFUSE_HOST") and not os.environ.get("LANGFUSE_BASE_URL"):
        os.environ["LANGFUSE_HOST"] = "https://langfuse.vibebrowser.app"

    try:
        import litellm

        # Enable Langfuse OTEL integration for automatic tracing
        if "langfuse_otel" not in (litellm.callbacks or []):
            litellm.callbacks = litellm.callbacks or []
            litellm.callbacks.append("langfuse_otel")
            logger.info("Langfuse OTEL integration enabled for LLM observability")

        return True
    except ImportError:
        logger.warning("litellm not installed, Langfuse integration disabled")
        return False
    except Exception as e:
        logger.warning(f"Failed to initialize Langfuse: {e}")
        return False


# Initialize Langfuse on import
_langfuse_enabled = _init_langfuse()

# Base exports (always available)
__all__ = [
    # Core
    "__version__",
]

# Primary exports - OpenHands-based (v3.x)
# Agent exports for direct usage - optional import for standalone connector usage
try:
    from vibeteam.agents import (  # noqa: F401
        BaseVibeAgent,
        MarketerAgent,
        ProductManagerAgent,
        ReleaseEngineerAgent,
        SoftwareEngineerAgent,
        SupportEngineerAgent,
    )
    from vibeteam.orchestrator import AgentType, TaskResult, VibeTeam  # noqa: F401

    __all__.extend(
        [
            # Orchestrator
            "VibeTeam",
            "AgentType",
            "TaskResult",
            # Agents
            "BaseVibeAgent",
            "ProductManagerAgent",
            "SoftwareEngineerAgent",
            "MarketerAgent",
            "SupportEngineerAgent",
            "ReleaseEngineerAgent",
        ]
    )
except ImportError:
    # Running in standalone mode (e.g., Docker containers with only connectors)
    # Agents and orchestrator not available
    logger.debug("vibeteam.agents/orchestrator not available - running in connector-only mode")
