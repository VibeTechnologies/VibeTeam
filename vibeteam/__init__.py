"""
VibeTeam - OpenHands-powered autonomous AI team for SaaS development.

This package provides autonomous agents that can:
- Monitor production (Sentry, Langfuse, health checks)
- Triage and classify issues
- Implement fixes and create PRs
- Review code and provide feedback

Agents:
- ReleaseEngineerAgent: Production monitoring and automated fixes
"""

import logging
import os

__version__ = "3.0.0"
__all__ = ["__version__"]

logger = logging.getLogger(__name__)


def _init_langfuse() -> bool:
    """
    Initialize Langfuse integration for LLM observability.

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

    logger.info("Langfuse configuration detected")
    return True


# Initialize Langfuse on import
_langfuse_enabled = _init_langfuse()
