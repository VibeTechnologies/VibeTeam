"""Shared LLM utilities for OpenHands agents.

Azure OpenAI doesn't support the Responses API endpoint. All agents must use
AzureLLM (which forces the completion API) instead of the base LLM class.

This module is the single source of truth for AzureLLM — do NOT define it
in individual agent files.
"""

from __future__ import annotations

try:
    from openhands.sdk import LLM

    OPENHANDS_LLM_AVAILABLE = True

    class AzureLLM(LLM):
        """LLM subclass that forces completion API for Azure OpenAI.

        Azure OpenAI doesn't support the Responses API endpoint, so we override
        uses_responses_api() to always return False. Without this, the SDK
        attempts to call the Responses API and gets a 404 from Azure.
        """

        def uses_responses_api(self) -> bool:
            """Azure OpenAI doesn't support the Responses API."""
            return False

except ImportError:
    OPENHANDS_LLM_AVAILABLE = False
    LLM = None  # type: ignore[assignment,misc]
    AzureLLM = None  # type: ignore[assignment,misc]


__all__ = ["AzureLLM", "LLM", "OPENHANDS_LLM_AVAILABLE"]
