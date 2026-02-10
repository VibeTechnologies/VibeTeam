"""Shared utilities for OpenHands agent implementations."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_response_from_events(events: list[Any]) -> str:
    """Extract the agent's final response from OpenHands conversation events.

    Checks events in reverse order (most recent first) for:
    1. ActionEvent with FinishAction/AgentFinishAction - extracts .message or .thought
    2. MessageEvent with source=="agent" - extracts text from .llm_message.content blocks

    FinishAction is checked first because when an agent calls finish(), that is the
    authoritative final response. MessageEvent is a fallback for agents that respond
    directly without using the finish tool.

    Args:
        events: List of OpenHands conversation events (from conversation.state.events).

    Returns:
        The extracted response string, or empty string if no response found.
    """
    response = ""

    for event in reversed(events):
        event_type = type(event).__name__

        # Check for ActionEvent containing FinishAction or AgentFinishAction
        if event_type == "ActionEvent":
            action = getattr(event, "action", None)
            action_name = type(action).__name__ if action else ""
            if action and action_name in ("FinishAction", "AgentFinishAction"):
                # Get message from the action
                message = getattr(action, "message", "")
                if message:
                    logger.info(
                        "Extracted response from %s.message (%d chars)",
                        action_name,
                        len(message),
                    )
                    response = message
                    break
                # Fallback to thought
                thought = getattr(action, "thought", "")
                if thought:
                    logger.info(
                        "Extracted response from %s.thought (%d chars)",
                        action_name,
                        len(thought),
                    )
                    response = thought
                    break

        # Check for MessageEvent (direct response without finish tool)
        elif event_type == "MessageEvent" and getattr(event, "source", None) == "agent":
            if hasattr(event, "llm_message") and event.llm_message:
                llm_msg = event.llm_message
                if hasattr(llm_msg, "content") and llm_msg.content:
                    for block in llm_msg.content:
                        if hasattr(block, "text") and block.text:
                            response = block.text
                            break
            if response:
                logger.info(
                    "Extracted response from MessageEvent (%d chars)",
                    len(response),
                )
                break

    if not response:
        # Log event types for debugging when no response is found
        event_types = [type(e).__name__ for e in events[-10:]] if events else []
        logger.warning(
            "No response extracted from %d events. Last 10 event types: %s",
            len(events),
            event_types,
        )

    return response
