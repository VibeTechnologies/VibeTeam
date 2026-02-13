"""
Progress callback factory for OpenHands agents.

Creates a reusable callback function that sends real-time progress updates
to the gateway while agents work. Uses OpenHands SDK's callback system
(ConversationCallbackType = Callable[[Event], None]) to intercept ActionEvents
and send summaries via HTTP POST.

Key design decisions:
- Callbacks fire synchronously inside conversation.run() which runs in a thread
- We use httpx sync client (not async) since we're in a sync thread context
- Rate-limited: at most one update every MIN_INTERVAL_SECONDS to avoid spam
- Uses ActionEvent.summary (~10 word LLM-generated description) when available,
  falls back to tool_name
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Minimum seconds between progress updates to avoid spamming Slack
MIN_INTERVAL_SECONDS = 8


def create_progress_callback(
    progress_url: str,
    job_id: str,
    callback_metadata: dict[str, Any],
    start_time: float | None = None,
) -> Callable[[Any], None]:
    """Create a callback function that sends progress updates to the gateway.

    The returned callback is compatible with OpenHands SDK's ConversationCallbackType
    (Callable[[Event], None]) and can be passed to LocalConversation(callbacks=[...]).

    Args:
        progress_url: URL to POST progress updates to (gateway's /callback/agent/progress)
        job_id: Job ID for correlation with the async request
        callback_metadata: Opaque metadata echoed back to gateway (contains channel, thread_ts, etc.)
        start_time: When the job started (defaults to now). Used to calculate elapsed_seconds.

    Returns:
        A callback function that can be passed to LocalConversation(callbacks=[callback])
    """
    _start = start_time or time.time()
    _step_counter = {"value": 0}
    _last_sent = {"time": 0.0}

    def _progress_callback(event: Any) -> None:
        """Called for every event during conversation.run().

        Filters for ActionEvents (agent tool calls) and sends progress summaries.
        Rate-limited to avoid flooding Slack with updates.
        """
        event_type = type(event).__name__

        # Only report on ActionEvents (tool calls), not observations or messages
        if event_type != "ActionEvent":
            return

        # Check rate limit
        now = time.time()
        if now - _last_sent["time"] < MIN_INTERVAL_SECONDS:
            return

        _step_counter["value"] += 1
        step_number = _step_counter["value"]

        # Build step summary from ActionEvent fields
        # ActionEvent has: tool_name (str), summary (str | None), thought (Sequence[TextContent])
        summary = ""
        try:
            # Prefer the LLM-generated summary (~10 words) if available
            if hasattr(event, "summary") and event.summary:
                summary = str(event.summary)
            elif hasattr(event, "tool_name") and event.tool_name:
                summary = f"Using {event.tool_name}"
            else:
                summary = "Processing..."
        except Exception:
            summary = "Processing..."

        # Truncate overly long summaries
        if len(summary) > 200:
            summary = summary[:197] + "..."

        elapsed = int(now - _start)

        # Send progress update (best-effort, non-blocking within this sync context)
        _send_progress_sync(
            progress_url=progress_url,
            job_id=job_id,
            step_number=step_number,
            step_summary=summary,
            elapsed_seconds=elapsed,
            callback_metadata=callback_metadata,
        )
        _last_sent["time"] = now

    return _progress_callback


def _send_progress_sync(
    progress_url: str,
    job_id: str,
    step_number: int,
    step_summary: str,
    elapsed_seconds: int,
    callback_metadata: dict[str, Any],
) -> None:
    """Send a progress update via synchronous HTTP POST (best-effort).

    This runs inside a sync thread (conversation.run's thread), so we use
    httpx sync client instead of async.
    """
    import httpx

    payload = {
        "job_id": job_id,
        "status": "in_progress",
        "step_number": step_number,
        "step_summary": step_summary,
        "elapsed_seconds": elapsed_seconds,
        "callback_metadata": callback_metadata,
    }

    try:
        with httpx.Client() as client:
            client.post(
                progress_url,
                json=payload,
                timeout=5.0,
            )
    except Exception as e:
        # Best-effort — don't let progress failures break the agent
        logger.debug(f"[job={job_id}] Failed to send progress update: {e}")
