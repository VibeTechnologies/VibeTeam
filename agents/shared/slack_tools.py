"""
Shared Slack tool functions for all agent frameworks.

These functions wrap the SlackConnector and provide a consistent interface
that can be used by AutoGen (as FunctionTool), CrewAI (wrapped in BaseTool),
and OpenHands (for context injection or post-processing).

All functions are async-compatible for AutoGen and can be called synchronously
for other frameworks.

Key Concept - Natural @Mentions:
    Agents write natural @mentions in their responses (e.g., "@SoftwareEngineer 
    please fix the login bug"). The bot parses these mentions and routes the
    conversation to the appropriate agent's session.
    
    This makes all inter-agent communication visible to humans in Slack.
"""

import os
from typing import Any

# Thread-local context for Slack operations
_slack_context: dict[str, Any] = {}


def _get_slack_connector():
    """Get Slack connector (lazy import to avoid init errors)."""
    from vibeteam.connectors.slack import SlackConnector

    try:
        return SlackConnector()
    except ValueError as e:
        return None, str(e)


# ==============================================================================
# Slack Context Management
# ==============================================================================


def set_slack_context(
    connector: Any,
    channel: str,
    thread_ts: str | None = None,
    from_agent: str | None = None,
) -> None:
    """
    Set Slack context for operations.

    Called by the Slack agent runner before processing a message.

    Args:
        connector: SlackConnector instance
        channel: Channel ID or name
        thread_ts: Thread timestamp (to keep responses in same thread)
        from_agent: Name of the agent setting context
    """
    global _slack_context
    _slack_context = {
        "connector": connector,
        "channel": channel,
        "thread_ts": thread_ts,
        "from_agent": from_agent,
    }


def get_slack_context() -> dict[str, Any]:
    """Get current Slack context."""
    return _slack_context


def clear_slack_context() -> None:
    """Clear Slack context after processing."""
    global _slack_context
    _slack_context = {}


def is_slack_context_set() -> bool:
    """Check if Slack context is set."""
    return bool(_slack_context.get("connector"))


# ==============================================================================
# Core Slack Tools (Async for AutoGen)
# ==============================================================================


async def post_slack_message(
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """
    Post a message to a Slack channel.

    Args:
        message: The message text to post
        channel: Channel name or ID (uses context or default if None)
        thread_ts: Thread timestamp to reply in (uses context if None)

    Returns:
        Confirmation with message timestamp
    """
    ctx = get_slack_context()
    connector = ctx.get("connector")

    if not connector:
        result = _get_slack_connector()
        if isinstance(result, tuple):
            return f"Slack error: {result[1]}"
        connector = result

    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")
    ts = thread_ts or ctx.get("thread_ts")

    try:
        result = connector.post_message(channel=ch, text=message, thread_ts=ts)
        return f"Posted to {ch} at {result.ts}"
    except Exception as e:
        return f"Error posting to Slack: {e}"


async def mention_agent(
    agent_key: str,
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """
    Mention another agent in Slack.

    This posts a message with an @mention that another agent's session
    will pick up.

    Args:
        agent_key: Agent to mention (swe, sre, release, support, pm, marketer)
        message: Message explaining the task/context
        channel: Channel to post in (uses context if None)
        thread_ts: Thread timestamp (uses context if None)

    Returns:
        Confirmation that message was posted

    Example:
        >>> await mention_agent("swe", "Please fix the login validation bug in auth.py")
        "Posted mention to @SoftwareEngineer in #ai-team"
    """
    ctx = get_slack_context()
    connector = ctx.get("connector")

    if not connector:
        result = _get_slack_connector()
        if isinstance(result, tuple):
            return f"Slack error: {result[1]}"
        connector = result

    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")
    ts = thread_ts or ctx.get("thread_ts")
    from_agent = ctx.get("from_agent", "Unknown")

    try:
        # Format message with agent mention
        agent_name = _get_agent_display_name(agent_key)
        mention_message = f"@{agent_name} {message}"
        if from_agent:
            mention_message = f"[From {from_agent}] {mention_message}"

        connector.mention_agent(
            channel=ch,
            agent_key=agent_key,
            message=mention_message,
            thread_ts=ts,
        )
        return f"Posted mention to @{agent_name} in {ch}"
    except Exception as e:
        return f"Error mentioning agent: {e}"


async def read_slack_channel(
    channel: str | None = None,
    limit: int = 10,
) -> str:
    """
    Read recent messages from a Slack channel.

    Args:
        channel: Channel name or ID (uses context if None)
        limit: Maximum messages to return (default: 10)

    Returns:
        Formatted string with recent messages
    """
    ctx = get_slack_context()
    connector = ctx.get("connector")

    if not connector:
        result = _get_slack_connector()
        if isinstance(result, tuple):
            return f"Slack error: {result[1]}"
        connector = result

    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")

    try:
        messages = connector.get_channel_history(channel=ch, limit=limit)

        if not messages:
            return f"No messages found in {ch}"

        result = f"=== Last {len(messages)} messages from {ch} ===\n\n"
        for msg in messages:
            user = msg.user or "bot"
            ts = msg.timestamp.strftime("%H:%M") if msg.timestamp else ""
            result += f"[{ts}] {user}: {msg.text[:200]}\n"

        return result
    except Exception as e:
        return f"Error reading channel: {e}"


async def read_slack_thread(
    thread_ts: str,
    channel: str | None = None,
    limit: int = 50,
) -> str:
    """
    Read messages from a Slack thread.

    Useful for understanding the full context of a conversation.

    Args:
        thread_ts: Thread parent timestamp
        channel: Channel name or ID (uses context if None)
        limit: Maximum messages to return (default: 50)

    Returns:
        Formatted string with thread messages
    """
    ctx = get_slack_context()
    connector = ctx.get("connector")

    if not connector:
        result = _get_slack_connector()
        if isinstance(result, tuple):
            return f"Slack error: {result[1]}"
        connector = result

    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")

    try:
        messages = connector.get_thread_replies(channel=ch, thread_ts=thread_ts, limit=limit)

        if not messages:
            return f"No messages found in thread"

        result = f"=== Thread ({len(messages)} messages) ===\n\n"
        for msg in messages:
            user = msg.user or "bot"
            ts = msg.timestamp.strftime("%H:%M") if msg.timestamp else ""
            result += f"[{ts}] {user}: {msg.text[:300]}\n"

        return result
    except Exception as e:
        return f"Error reading thread: {e}"


# ==============================================================================
# Sync Versions (for CrewAI and OpenHands)
# ==============================================================================


def post_slack_message_sync(
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """Synchronous version of post_slack_message."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(
        post_slack_message(message, channel, thread_ts)
    )


def mention_agent_sync(
    agent_key: str,
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """Synchronous version of mention_agent."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(
        mention_agent(agent_key, message, channel, thread_ts)
    )


def read_slack_channel_sync(channel: str | None = None, limit: int = 10) -> str:
    """Synchronous version of read_slack_channel."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(read_slack_channel(channel, limit))


def read_slack_thread_sync(
    thread_ts: str,
    channel: str | None = None,
    limit: int = 50,
) -> str:
    """Synchronous version of read_slack_thread."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(read_slack_thread(thread_ts, channel, limit))


# ==============================================================================
# Context Injection (for OpenHands)
# ==============================================================================


def get_slack_context_for_injection(channel: str | None = None, limit: int = 5) -> str:
    """
    Get Slack context for injection into OpenHands prompts.

    Args:
        channel: Channel to read from
        limit: Number of recent messages

    Returns:
        Formatted context string for prompt injection
    """
    try:
        result = _get_slack_connector()
        if isinstance(result, tuple):
            return f"Slack: Not available - {result[1]}"

        connector = result
        ch = channel or os.getenv("SLACK_CHANNEL", "#ai-team")
        messages = connector.get_channel_history(channel=ch, limit=limit)

        if not messages:
            return f"Slack: No recent messages in {ch}"

        context = f"=== Recent Slack Messages ({ch}) ===\n\n"
        for msg in messages:
            user = msg.user or "bot"
            context += f"[{user}]: {msg.text[:200]}\n"

        return context
    except Exception as e:
        return f"Slack: Error - {e}"


def get_slack_handoff_instructions() -> str:
    """
    Get instructions for agent handoffs (for agent system prompts).

    Returns:
        Instructions string to include in agent prompts
    """
    return """
## TEAM COLLABORATION

When you need help from another team member, @mention them naturally in your response:
- @SoftwareEngineer - for code implementation, bug fixes, PRs
- @ReleaseEngineer - for deployments and releases
- @SupportEngineer - for customer communication
- @SiteReliabilityEngineer - for monitoring, Sentry errors, infrastructure
- @MarketingManager - for announcements and content
- @ProductManager - for requirements and prioritization

Example: "I've analyzed the request. @SoftwareEngineer please implement the login validation fix."

The mentioned agent will automatically pick up the conversation.
Always provide clear context when handing off so the receiving agent
can understand and work on the task effectively.
"""


# ==============================================================================
# Helpers
# ==============================================================================


def _get_agent_display_name(agent_key: str) -> str:
    """Get display name for an agent key."""
    display_names = {
        "swe": "SoftwareEngineer",
        "sre": "SiteReliabilityEngineer",
        "release": "ReleaseEngineer",
        "support": "SupportEngineer",
        "pm": "ProductManager",
        "marketer": "MarketingManager",
        "supervisor": "ProductManager",
    }
    return display_names.get(agent_key.lower(), agent_key)
