"""
VibeTeam - Autonomous AI team for SaaS development.

This package provides a multi-agent system with specialized roles:
- ProductManager: Defines requirements, roadmap, user stories
- SoftwareEngineer: Implements features, fixes bugs, writes tests
- Marketer: Creates content, social media posts, announcements
- SupportEngineer: Handles user issues, documentation, FAQ
- ReliabilityEngineer: Monitors production, handles incidents
- ReleaseEngineer: Manages deployments, versioning, releases

Migration Status:
- v2.x: MetaGPT-based (legacy, being deprecated)
- v3.x: OpenHands SDK-based (new architecture)
"""

import logging
import os

__version__ = "3.0.0"
__all__ = ["__version__"]

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


# Lazy imports to support migration period
# MetaGPT-based imports (legacy) - only work if metagpt is installed
def _get_vibe_team_legacy():
    """Get legacy MetaGPT-based VibeTeam (deprecated)."""
    try:
        from vibeteam.team import VibeTeam
        return VibeTeam
    except ImportError:
        raise ImportError(
            "MetaGPT is not installed. Use the new OpenHands-based API:\n"
            "  from vibeteam.agents import BaseVibeAgent"
        )


# OpenHands-based imports (new)
def _get_base_vibe_agent():
    """Get new OpenHands-based BaseVibeAgent."""
    from vibeteam.agents.base import BaseVibeAgent
    return BaseVibeAgent


# For backwards compatibility, try to import VibeTeam
# This will fail gracefully if metagpt is not installed
try:
    from vibeteam.team import VibeTeam
    __all__.append("VibeTeam")
except ImportError:
    # MetaGPT not installed - only new API available
    VibeTeam = None
    logger.info("MetaGPT not installed. Using OpenHands-based agents only.")
