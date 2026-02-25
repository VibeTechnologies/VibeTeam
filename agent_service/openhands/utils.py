"""Shared utilities for OpenHands agent implementations."""

from __future__ import annotations

import logging
import os
from typing import Any

from agents.shared.llm import get_model_context_window, resolve_azure_model

logger = logging.getLogger(__name__)

# Base directory for the agents/openhands package.
# In the dev k8s overlay, code lives under /code/current (a symlink managed by
# git-sync that points to a worktree directory named after the commit SHA).
# When git-sync updates, it atomically swaps the symlink to a new worktree and
# removes the old one.  Python's __file__ is resolved at import time and caches
# the *resolved* (non-symlink) path, so after a git-sync update __file__ points
# to a deleted directory.
#
# We solve this by resolving the path from the symlink at *call* time rather
# than at import time.
_CODE_CURRENT = "/code/current"

# Default text content limit override (characters). We set this higher than the
# OpenHands SDK default (50k) to avoid premature truncation when larger context
# windows are available.
DEFAULT_TEXT_CONTENT_LIMIT = 200_000
DISABLE_TEXT_CONTENT_LIMIT = 2_000_000_000
DEFAULT_CONDENSE_TOKEN_RATIO = 0.7
_TEXTCONTENT_JSON_PATCHED = False


def _get_context_window_from_env() -> tuple[str | None, int | None]:
    model = (
        os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("OPENAI_DEPLOYMENT")
    )
    api_base = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_API_BASE")
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
    api_version = os.getenv("AZURE_API_VERSION")

    model = resolve_azure_model(model, api_base=api_base, api_version=api_version)

    ctx_tokens = get_model_context_window(
        model,
        api_base=api_base or os.getenv("OPENAI_API_BASE"),
        api_key=api_key or os.getenv("OPENAI_API_KEY"),
        api_version=api_version,
    )
    return model, ctx_tokens


def configure_text_truncation() -> None:
    """Configure OpenHands TextContent truncation limit.

    OpenHands SDK hard-caps TextContent at 50k chars. We raise the limit so
    larger context windows (e.g., GPT-5.2) can be utilized without truncation.

    Set OPENHANDS_TEXT_CONTENT_LIMIT to override the default (200k). Set it to
    0 or a negative value to disable truncation (very large limit).
    """
    limit_raw = os.getenv("OPENHANDS_TEXT_CONTENT_LIMIT")
    model_name, ctx_tokens = _get_context_window_from_env()
    if ctx_tokens:
        logger.info(
            "Model %s context window (API): %d tokens",
            model_name or "unknown",
            ctx_tokens,
        )
    else:
        logger.info("Model context window not available via API")
    if limit_raw is None or limit_raw == "":
        if ctx_tokens:
            # Rough char estimate (~4 chars per token).
            estimated = int(ctx_tokens * 4)
            limit = max(DEFAULT_TEXT_CONTENT_LIMIT, estimated)
        else:
            limit = DEFAULT_TEXT_CONTENT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            logger.warning(
                "Invalid OPENHANDS_TEXT_CONTENT_LIMIT=%r; using default %d",
                limit_raw,
                DEFAULT_TEXT_CONTENT_LIMIT,
            )
            limit = DEFAULT_TEXT_CONTENT_LIMIT

    if limit <= 0:
        # Explicitly disable truncation by setting a very large limit.
        limit = DISABLE_TEXT_CONTENT_LIMIT
        logger.info("OPENHANDS_TEXT_CONTENT_LIMIT <= 0; disabling truncation")

    try:
        from openhands.sdk.llm import message as oh_message
        from openhands.sdk.utils import truncate as oh_truncate

        oh_message.DEFAULT_TEXT_CONTENT_LIMIT = limit
        oh_truncate.DEFAULT_TEXT_CONTENT_LIMIT = limit
        logger.info("Set OpenHands TextContent limit to %d chars", limit)
    except Exception as e:
        logger.warning("Failed to configure OpenHands text truncation: %s", e)


def configure_textcontent_json_serialization() -> None:
    """Patch OpenHands JSON serialization to handle TextContent safely.

    OpenHands SDK logs LLM messages with json.dumps() in agent.py. The model
    dumps include TextContent objects that are not JSON-serializable, which
    crashes the agent loop. We patch the JSON encoder and the agent module's
    json.dumps to safely coerce TextContent into plain strings.
    """
    global _TEXTCONTENT_JSON_PATCHED
    if _TEXTCONTENT_JSON_PATCHED:
        return

    try:
        from openhands.sdk.llm import TextContent  # type: ignore
        import openhands.sdk.agent.agent as agent_mod  # type: ignore
        import json as _json

        def _safe_default(obj):
            if isinstance(obj, TextContent):
                return obj.text
            return str(obj)

        def _safe_dumps(obj, **kwargs):
            # Respect caller-provided default if present
            if "default" not in kwargs:
                kwargs["default"] = _safe_default
            return _json.dumps(obj, **kwargs)

        # Patch the agent module's json.dumps used in debug logging
        agent_mod.json.dumps = _safe_dumps  # type: ignore[assignment]

        # Patch OpenHands JSON encoders used elsewhere (event serialization)
        try:
            from openhands.io.json import OpenHandsJSONEncoder as IOEncoder  # type: ignore

            _io_default = IOEncoder.default

            def _io_default_wrapped(self, obj):  # type: ignore[no-self-use]
                if isinstance(obj, TextContent):
                    return obj.text
                return _io_default(self, obj)

            IOEncoder.default = _io_default_wrapped  # type: ignore[assignment]
        except Exception:
            pass

        try:
            from openhands.sdk.utils.json import (  # type: ignore
                OpenHandsJSONEncoder as SDKEncoder,
            )

            _sdk_default = SDKEncoder.default

            def _sdk_default_wrapped(self, obj):  # type: ignore[no-self-use]
                if isinstance(obj, TextContent):
                    return obj.text
                return _sdk_default(self, obj)

            SDKEncoder.default = _sdk_default_wrapped  # type: ignore[assignment]
        except Exception:
            pass

        _TEXTCONTENT_JSON_PATCHED = True
        logger.info("Patched OpenHands JSON serialization for TextContent")
    except Exception as e:
        logger.warning("Failed to patch OpenHands JSON serialization: %s", e)


def build_condenser(llm: Any) -> Any | None:
    """Create an OpenHands condenser to auto-compact long conversations.

    Controlled via env vars:
    - OPENHANDS_CONDENSE_MAX_EVENTS (default 120)
    - OPENHANDS_CONDENSE_MAX_TOKENS (default 120000; set empty to disable token-based)
    - OPENHANDS_CONDENSE_KEEP_FIRST (default 4)
    """
    try:
        from openhands.sdk.context.condenser import LLMSummarizingCondenser
    except Exception as e:
        logger.warning("OpenHands condenser unavailable: %s", e)
        return None

    max_events_raw = os.getenv("OPENHANDS_CONDENSE_MAX_EVENTS", "120")
    keep_first_raw = os.getenv("OPENHANDS_CONDENSE_KEEP_FIRST", "4")
    max_tokens_raw = os.getenv("OPENHANDS_CONDENSE_MAX_TOKENS")
    token_ratio_raw = os.getenv("OPENHANDS_CONDENSE_TOKEN_RATIO", str(DEFAULT_CONDENSE_TOKEN_RATIO))

    try:
        max_events = int(max_events_raw)
    except ValueError:
        max_events = 120
    try:
        keep_first = int(keep_first_raw)
    except ValueError:
        keep_first = 4

    max_tokens = None
    if max_tokens_raw is not None and max_tokens_raw != "":
        try:
            max_tokens_val = int(max_tokens_raw)
            if max_tokens_val > 0:
                max_tokens = max_tokens_val
        except ValueError:
            max_tokens = None
    else:
        # If not explicitly set, derive from API model context window (if available).
        _, ctx_tokens = _get_context_window_from_env()
        if ctx_tokens:
            try:
                ratio = float(token_ratio_raw)
            except ValueError:
                ratio = DEFAULT_CONDENSE_TOKEN_RATIO
            if ratio > 0:
                max_tokens = int(ctx_tokens * ratio)

    if max_events <= 0 and max_tokens is None:
        return None

    return LLMSummarizingCondenser(
        llm=llm,
        max_size=max_events,
        max_tokens=max_tokens,
        keep_first=max(0, keep_first),
    )


def get_prompt_path(prompt_filename: str = "agent_system.j2") -> str:
    """Return the absolute path to a prompt template in agent_service/openhands/prompts/.

    Resolves through the /code/current symlink at call time so the path stays
    valid even after git-sync replaces the underlying worktree.  Falls back to
    ``os.path.dirname(__file__)`` for local development where /code/current
    does not exist.

    Args:
        prompt_filename: The template filename (default: ``agent_system.j2``).

    Returns:
        Absolute path to the prompt template file.
    """
    if os.path.isdir(_CODE_CURRENT):
        return os.path.join(_CODE_CURRENT, "agent_service", "openhands", "prompts", prompt_filename)
    # Local dev / non-k8s fallback
    return os.path.join(os.path.dirname(__file__), "prompts", prompt_filename)


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

                # Look ahead for the next observation (output of this action).
                # OpenHands observation types: CmdOutputObservation, FileReadObservation,
                # FileEditObservation, etc. — all end with "Observation" and have .message.
                if i + 1 < len(events):
                    next_event = events[i + 1]
                    next_type = type(next_event).__name__
                    if next_type.endswith("Observation"):
                        # Primary: .message (all OpenHands observations have this)
                        obs_content = getattr(next_event, "message", "")
                        if not obs_content:
                            # Fallback: .content or .text (for custom/mock events)
                            obs_content = getattr(next_event, "content", "") or getattr(
                                next_event, "text", ""
                            )
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
