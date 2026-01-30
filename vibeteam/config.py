"""
Centralized configuration for VibeTeam.

All configurable settings should be defined here to avoid duplication.
Settings can be overridden via environment variables.
"""

import os

# =============================================================================
# LLM Configuration
# =============================================================================

# Default model for all agents (can be overridden per-agent or via env)
DEFAULT_MODEL = os.environ.get("VIBETEAM_MODEL", "azure/gpt-5-2")

# Default temperature for agents
DEFAULT_TEMPERATURE = float(os.environ.get("VIBETEAM_TEMPERATURE", "0.3"))

# Default max tokens
DEFAULT_MAX_TOKENS = int(os.environ.get("VIBETEAM_MAX_TOKENS", "4096"))


# =============================================================================
# Slack Configuration
# =============================================================================

SLACK_DEFAULT_CHANNEL = os.environ.get("SLACK_DEFAULT_CHANNEL", "#ai-team")


# =============================================================================
# API Configuration
# =============================================================================

# Langfuse host for LLM observability
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://langfuse.vibebrowser.app")
