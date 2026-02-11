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
                # Fallback to thought (check both action and event)
                thought = getattr(action, "thought", "") or getattr(event, "thought", "")
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
        # Fallback 1: Look for ThinkAction — agent used think() tool which
        # stores its reasoning in action.thought.  This is separate from the
        # ActionEvent.thought field (which gpt-4.1-mini rarely populates).
        for event in reversed(events):
            event_type = type(event).__name__
            if event_type == "ActionEvent":
                action = getattr(event, "action", None)
                action_name = type(action).__name__ if action else ""
                if action_name == "ThinkAction":
                    thought = getattr(action, "thought", "")
                    if thought:
                        logger.info(
                            "Extracted response from ThinkAction.thought fallback (%d chars)",
                            len(thought),
                        )
                        response = thought
                        break

    if not response:
        # Fallback 2: extract the last ActionEvent's thought field.
        # When the agent hits max_iterations without calling finish(), the last
        # action's thought often contains the LLM's summary/reasoning.
        # NOTE: thought is on the ActionEvent itself, NOT on the action object.
        # e.g. TerminalAction has [command, is_input, timeout, reset] but no thought.
        for event in reversed(events):
            event_type = type(event).__name__
            if event_type == "ActionEvent":
                # thought lives on the ActionEvent, not on event.action
                thought = getattr(event, "thought", "")
                if thought:
                    action = getattr(event, "action", None)
                    action_name = type(action).__name__ if action else "?"
                    logger.info(
                        "Extracted response from last ActionEvent.thought fallback (%s, %d chars)",
                        action_name,
                        len(thought),
                    )
                    response = thought
                    break

    if not response:
        # Fallback 3: Compose from action summaries + observation outputs.
        # This produces a rich response showing both what the agent did AND what it found.
        # We pair ActionEvents with their following ObservationEvents to include outputs.
        steps: list[str] = []
        max_obs_chars = 500  # Truncate each observation to avoid huge responses

        # Walk forward to pair actions with observations
        i = 0
        while i < len(events):
            event = events[i]
            event_type = type(event).__name__

            if event_type == "ActionEvent":
                action = getattr(event, "action", None)
                action_name = type(action).__name__ if action else ""
                # Skip FinishAction/AgentFinishAction — already handled above
                if action_name in ("FinishAction", "AgentFinishAction"):
                    i += 1
                    continue

                summary = getattr(event, "summary", "")
                if not summary:
                    i += 1
                    continue

                step = f"- {summary}"

                # Look ahead for the next ObservationEvent (output of this action)
                if i + 1 < len(events):
                    next_event = events[i + 1]
                    next_type = type(next_event).__name__
                    if next_type == "ObservationEvent":
                        obs_content = getattr(next_event, "content", "")
                        if not obs_content:
                            # Try .text or str fallback
                            obs_content = getattr(next_event, "text", "")
                        if obs_content and len(obs_content.strip()) > 0:
                            obs_text = obs_content.strip()
                            if len(obs_text) > max_obs_chars:
                                obs_text = obs_text[:max_obs_chars] + "..."
                            step += f"\n  ```\n  {obs_text}\n  ```"
                        i += 1  # Skip the observation event

                steps.append(step)
            i += 1

        # Take the last 8 steps to keep the response focused
        if steps:
            recent_steps = steps[-8:]
            response = (
                "I investigated but ran out of iterations before completing. "
                "Here's what I did and found:\n\n" + "\n".join(recent_steps)
            )
            logger.info(
                "Composed response from %d action+observation pairs (%d chars)",
                len(recent_steps),
                len(response),
            )

    if not response:
        # Log event types for debugging when no response is found
        event_summary = []
        for e in events[-10:] if events else []:
            etype = type(e).__name__
            if etype == "ActionEvent":
                action = getattr(e, "action", None)
                aname = type(action).__name__ if action else "?"
                etype = f"ActionEvent({aname})"
            event_summary.append(etype)
        logger.warning(
            "No response extracted from %d events. Last 10: %s",
            len(events),
            event_summary,
        )

    return response
