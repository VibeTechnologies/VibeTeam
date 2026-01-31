"""
Shared Slack tool functions for all agent frameworks.

These functions wrap the SlackConnector and provide a consistent interface
that can be used by AutoGen (as FunctionTool), CrewAI (wrapped in BaseTool),
and OpenHands (for context injection or post-processing).

All functions are async-compatible for AutoGen and can be called synchronously
for other frameworks.

Key Concept - Slack-based Handoffs:
    All agents subscribe to a Slack channel as message listeners. When an agent
    needs to delegate work, it @mentions another agent in Slack. The receiving
    agent's listener picks up the message and processes it.

    This makes all inter-agent communication visible to humans in Slack.
"""

import os
from typing import Any

# Thread-local context for Slack handoffs
_slack_handoff_context: dict[str, Any] = {}


def _get_slack_connector():
    """Get Slack connector (lazy import to avoid init errors)."""
    from vibeteam.connectors.slack import SlackConnector

    try:
        return SlackConnector()
    except ValueError as e:
        return None, str(e)


# ==============================================================================
# Slack Handoff Context Management
# ==============================================================================


def set_slack_context(
    connector: Any,
    channel: str,
    thread_ts: str | None = None,
    from_agent: str | None = None,
) -> None:
    """
    Set Slack context for handoffs.

    Called by the Slack agent runner before processing a message.
    This enables transfer tools to post @mentions to Slack.

    Args:
        connector: SlackConnector instance
        channel: Channel ID or name
        thread_ts: Thread timestamp (to keep handoffs in same thread)
        from_agent: Name of the agent setting context
    """
    global _slack_handoff_context
    _slack_handoff_context = {
        "connector": connector,
        "channel": channel,
        "thread_ts": thread_ts,
        "from_agent": from_agent,
    }


def get_slack_context() -> dict[str, Any]:
    """Get current Slack handoff context."""
    return _slack_handoff_context


def clear_slack_context() -> None:
    """Clear Slack handoff context after processing."""
    global _slack_handoff_context
    _slack_handoff_context = {}


def is_slack_context_set() -> bool:
    """Check if Slack context is set for handoffs."""
    return bool(_slack_handoff_context.get("connector"))


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
    Mention another agent in Slack to hand off a task.

    This is the primary method for inter-agent communication. The receiving
    agent's Slack listener will pick up this @mention and process the task.

    Args:
        agent_key: Agent to mention (swe, sre, release, support, pm, marketer)
        message: Message explaining the task/context
        channel: Channel to post in (uses context if None)
        thread_ts: Thread timestamp (uses context if None)

    Returns:
        Confirmation that handoff was posted

    Example:
        >>> await mention_agent("swe", "Please fix the login validation bug in auth.py")
        "Handed off to @swe in #ai-team"
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
        # Format handoff message
        handoff_message = (
            f"I need help from {_get_agent_display_name(agent_key)}.\n\n**Task:** {message}"
        )
        if from_agent:
            handoff_message = f"[From {from_agent}] {handoff_message}"

        connector.mention_agent(
            channel=ch,
            agent_key=agent_key,
            message=handoff_message,
            thread_ts=ts,
        )
        return f"Handed off to @{agent_key} in {ch}"
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

    Useful for understanding the full context of a conversation before
    responding or handing off to another agent.

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
# Transfer Tools (Convenience wrappers for specific agents)
# ==============================================================================


async def transfer_to_swe(task: str, context: str = "") -> str:
    """
    Transfer a task to SoftwareEngineer for code implementation or bug fixes.

    Use this when you identify issues that require code changes, new features,
    or debugging.

    Args:
        task: Description of the coding task
        context: Additional context (error logs, requirements, etc.)

    Returns:
        Confirmation that handoff was posted to Slack
    """
    message = task
    if context:
        message += f"\n\n**Context:** {context}"
    return await mention_agent("swe", message)


async def transfer_to_sre(task: str, context: str = "") -> str:
    """
    Transfer a task to SiteReliabilityEngineer for infrastructure issues.

    Use this for monitoring alerts, Sentry errors, latency issues,
    deployment problems, or infrastructure investigations.

    Args:
        task: Description of the infrastructure issue
        context: Additional context (error messages, metrics, etc.)

    Returns:
        Confirmation that handoff was posted to Slack
    """
    message = task
    if context:
        message += f"\n\n**Context:** {context}"
    return await mention_agent("sre", message)


async def transfer_to_release(task: str, context: str = "") -> str:
    """
    Transfer a task to ReleaseEngineer for deployments and releases.

    Use this when code is ready for deployment, releases need to be
    created, or deployment issues need investigation.

    Args:
        task: Description of the release/deployment task
        context: Additional context (PR numbers, version, etc.)

    Returns:
        Confirmation that handoff was posted to Slack
    """
    message = task
    if context:
        message += f"\n\n**Context:** {context}"
    return await mention_agent("release", message)


async def transfer_to_support(task: str, context: str = "") -> str:
    """
    Transfer a task to SupportEngineer for customer issues.

    Use this for customer-facing issues, support tickets, or when
    customer communication is needed.

    Args:
        task: Description of the support task
        context: Additional context (customer info, ticket details, etc.)

    Returns:
        Confirmation that handoff was posted to Slack
    """
    message = task
    if context:
        message += f"\n\n**Context:** {context}"
    return await mention_agent("support", message)


async def transfer_to_pm(task: str, context: str = "") -> str:
    """
    Transfer a task to ProductManager for prioritization or requirements.

    Use this for feature requests, product decisions, or when
    prioritization/roadmap input is needed.

    Args:
        task: Description of the product/prioritization task
        context: Additional context (customer feedback, requirements, etc.)

    Returns:
        Confirmation that handoff was posted to Slack
    """
    message = task
    if context:
        message += f"\n\n**Context:** {context}"
    return await mention_agent("pm", message)


async def transfer_to_marketer(task: str, context: str = "") -> str:
    """
    Transfer a task to MarketingManager for announcements or social media.

    Use this when releases need to be announced, social media posts
    are needed, or marketing communication is required.

    Args:
        task: Description of the marketing task
        context: Additional context (release notes, timing, etc.)

    Returns:
        Confirmation that handoff was posted to Slack
    """
    message = task
    if context:
        message += f"\n\n**Context:** {context}"
    return await mention_agent("marketer", message)


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


# Transfer tool sync versions
def transfer_to_swe_sync(task: str, context: str = "") -> str:
    """Synchronous version of transfer_to_swe."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(transfer_to_swe(task, context))


def transfer_to_sre_sync(task: str, context: str = "") -> str:
    """Synchronous version of transfer_to_sre."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(transfer_to_sre(task, context))


def transfer_to_release_sync(task: str, context: str = "") -> str:
    """Synchronous version of transfer_to_release."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(transfer_to_release(task, context))


def transfer_to_support_sync(task: str, context: str = "") -> str:
    """Synchronous version of transfer_to_support."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(transfer_to_support(task, context))


def transfer_to_pm_sync(task: str, context: str = "") -> str:
    """Synchronous version of transfer_to_pm."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(transfer_to_pm(task, context))


def transfer_to_marketer_sync(task: str, context: str = "") -> str:
    """Synchronous version of transfer_to_marketer."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(transfer_to_marketer(task, context))


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
    Get instructions for Slack-based handoffs (for agent system prompts).

    Returns:
        Instructions string to include in agent prompts
    """
    return """
## TEAM HANDOFFS (via Slack)

When you need help from another team member, use the transfer tools to post
@mentions in Slack. The receiving agent will pick up your message and work on it.

Available transfer tools:
- transfer_to_swe(task, context): For code bugs, features, PRs
- transfer_to_sre(task, context): For monitoring, Sentry, infrastructure
- transfer_to_release(task, context): For deployments, releases
- transfer_to_support(task, context): For customer issues, tickets
- transfer_to_pm(task, context): For prioritization, requirements
- transfer_to_marketer(task, context): For announcements, social media

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
