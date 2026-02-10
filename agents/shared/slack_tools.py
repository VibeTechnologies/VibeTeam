"""
Standalone Slack tools for OpenHands and other agent frameworks.

This module provides Slack functionality WITHOUT depending on vibeteam package.
It uses slack_sdk directly, making it suitable for containerized deployments
where only the agents/ directory is available.

Key Concept - /RoleName Mentions:
    Agents use /RoleName mentions in their responses (e.g., "/SoftwareEngineer
    please fix the login bug"). The router parses these mentions and routes the
    conversation to the appropriate agent's session.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Default timeout for Slack API calls
DEFAULT_TIMEOUT = 10


@dataclass
class SlackMessage:
    """Represents a Slack message."""

    ts: str  # Message timestamp (unique ID)
    channel: str
    user: str
    text: str
    thread_ts: str | None  # Parent thread timestamp
    timestamp: datetime | None  # When the message was sent
    is_bot: bool
    mentions: list[str]  # User IDs mentioned

    @property
    def permalink(self) -> str:
        """Generate a permalink-style reference."""
        return f"{self.channel}/{self.ts}"


@dataclass
class SlackChannel:
    """Represents a Slack channel."""

    id: str
    name: str
    is_private: bool
    is_member: bool
    topic: str
    purpose: str


class SlackClient:
    """
    Lightweight Slack API client using slack_sdk directly.

    This is a standalone implementation that doesn't depend on vibeteam.

    Usage:
        client = SlackClient()  # Uses SLACK_BOT_TOKEN env var

        # Post message
        client.post_message("#ai-team", "Hello!")

        # Read channel history
        messages = client.get_channel_history("#ai-team", limit=10)

        # Reply in thread
        client.post_message("#ai-team", "Following up...", thread_ts=msg.ts)
    """

    def __init__(
        self,
        token: str | None = None,
        default_channel: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        Initialize Slack client.

        Args:
            token: Slack bot token (or from SLACK_BOT_TOKEN env)
            default_channel: Default channel for messages
            timeout: Request timeout in seconds
        """
        self.token = token or os.environ.get("SLACK_BOT_TOKEN")
        self.default_channel = default_channel or os.environ.get(
            "SLACK_DEFAULT_CHANNEL", "#ai-team"
        )
        self.timeout = timeout

        if not self.token:
            raise ValueError("Slack token required. Set SLACK_BOT_TOKEN env var or pass token.")

        # Import slack_sdk here to fail fast if not available
        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError

            self.WebClient = WebClient
            self.SlackApiError = SlackApiError
        except ImportError as e:
            raise ImportError("slack_sdk is required. Install with: pip install slack_sdk") from e

        self.client = self.WebClient(token=self.token, timeout=self.timeout)
        self._bot_user_id: str | None = None
        self._channel_cache: dict[str, str] = {}  # name -> id

    @property
    def bot_user_id(self) -> str:
        """Get the bot's user ID (lazy loaded)."""
        if self._bot_user_id is None:
            response = self.client.auth_test()
            self._bot_user_id = response["user_id"]
        return self._bot_user_id

    def _resolve_channel(self, channel: str) -> str:
        """
        Resolve channel name to ID.

        Args:
            channel: Channel name (with or without #) or ID

        Returns:
            Channel ID
        """
        # Already an ID
        if channel.startswith("C") or channel.startswith("D"):
            return channel

        # Remove # prefix
        name = channel.lstrip("#")

        # Check cache
        if name in self._channel_cache:
            return self._channel_cache[name]

        # Look up channel
        try:
            response = self.client.conversations_list(types="public_channel,private_channel")
            for ch in response.get("channels", []):
                self._channel_cache[ch["name"]] = ch["id"]
                if ch["name"] == name:
                    return ch["id"]
        except self.SlackApiError:
            pass

        # Return as-is if not found (might be a DM or already resolved)
        return channel

    def _parse_message(self, data: dict, channel: str) -> SlackMessage:
        """Parse API response into SlackMessage."""
        text = data.get("text", "")
        mentions = re.findall(r"<@(U[A-Z0-9]+)>", text)

        ts_float = float(data.get("ts", "0"))
        timestamp = datetime.fromtimestamp(ts_float)

        return SlackMessage(
            ts=data.get("ts", ""),
            channel=channel,
            user=data.get("user", ""),
            text=text,
            thread_ts=data.get("thread_ts"),
            timestamp=timestamp,
            is_bot=data.get("bot_id") is not None,
            mentions=mentions,
        )

    def post_message(
        self,
        channel: str | None = None,
        text: str = "",
        thread_ts: str | None = None,
        blocks: list[dict] | None = None,
    ) -> SlackMessage:
        """
        Post a message to a channel.

        Args:
            channel: Channel name or ID (uses default if None)
            text: Message text
            thread_ts: Thread timestamp to reply to
            blocks: Block Kit blocks for rich formatting

        Returns:
            The posted message
        """
        channel = channel or self.default_channel
        channel_id = self._resolve_channel(channel)

        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "text": text,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        if blocks:
            kwargs["blocks"] = blocks

        response = self.client.chat_postMessage(**kwargs)

        return SlackMessage(
            ts=response["ts"],
            channel=channel_id,
            user=self.bot_user_id,
            text=text,
            thread_ts=thread_ts,
            timestamp=datetime.now(),
            is_bot=True,
            mentions=[],
        )

    def add_reaction(
        self,
        channel: str,
        timestamp: str,
        emoji: str = "eyes",
    ) -> bool:
        """
        Add a reaction emoji to a message.

        Args:
            channel: Channel ID where the message is
            timestamp: Message timestamp (ts)
            emoji: Emoji name without colons (default: "eyes")

        Returns:
            True if reaction was added successfully
        """
        try:
            self.client.reactions_add(
                channel=channel,
                timestamp=timestamp,
                name=emoji,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to add reaction: {e}")
            return False

    def get_channel_history(
        self,
        channel: str | None = None,
        limit: int = 20,
        oldest: str | None = None,
        latest: str | None = None,
    ) -> list[SlackMessage]:
        """
        Get channel message history.

        Args:
            channel: Channel name or ID
            limit: Maximum messages to return
            oldest: Only messages after this timestamp
            latest: Only messages before this timestamp

        Returns:
            List of messages (newest first)
        """
        channel = channel or self.default_channel
        channel_id = self._resolve_channel(channel)

        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "limit": limit,
        }
        if oldest:
            kwargs["oldest"] = oldest
        if latest:
            kwargs["latest"] = latest

        response = self.client.conversations_history(**kwargs)

        return [self._parse_message(msg, channel_id) for msg in response.get("messages", [])]

    def get_thread_replies(
        self,
        channel: str,
        thread_ts: str,
        limit: int = 100,
    ) -> list[SlackMessage]:
        """
        Get replies in a thread.

        Args:
            channel: Channel name or ID
            thread_ts: Parent message timestamp
            limit: Maximum replies to return

        Returns:
            List of thread messages
        """
        channel_id = self._resolve_channel(channel)

        response = self.client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=limit,
        )

        return [self._parse_message(msg, channel_id) for msg in response.get("messages", [])]

    def list_channels(self, include_private: bool = False) -> list[SlackChannel]:
        """
        List available channels.

        Args:
            include_private: Include private channels

        Returns:
            List of channels the bot has access to
        """
        types = "public_channel"
        if include_private:
            types += ",private_channel"

        response = self.client.conversations_list(types=types)

        channels = []
        for ch in response.get("channels", []):
            channels.append(
                SlackChannel(
                    id=ch["id"],
                    name=ch["name"],
                    is_private=ch.get("is_private", False),
                    is_member=ch.get("is_member", False),
                    topic=ch.get("topic", {}).get("value", ""),
                    purpose=ch.get("purpose", {}).get("value", ""),
                )
            )

        return channels


# ==============================================================================
# Thread-local context for Slack operations
# ==============================================================================

_slack_context: dict[str, Any] = {}


def set_slack_context(
    client: SlackClient | Any,
    channel: str,
    thread_ts: str | None = None,
    from_agent: str | None = None,
    session_id: str | None = None,
) -> None:
    """
    Set Slack context for operations.

    Called by the Slack agent runner before processing a message.

    Args:
        client: SlackClient instance
        channel: Channel ID or name
        thread_ts: Thread timestamp (to keep responses in same thread)
        from_agent: Name of the agent setting context (e.g., "SupportEngineer")
        session_id: Session ID for message prefix (e.g., "abc123")
    """
    global _slack_context
    _slack_context = {
        "client": client,
        "channel": channel,
        "thread_ts": thread_ts,
        "from_agent": from_agent,
        "session_id": session_id,
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
    return bool(_slack_context.get("client"))


# ==============================================================================
# High-level functions for agents
# ==============================================================================


def _get_slack_client() -> SlackClient | tuple[None, str]:
    """Get or create Slack client."""
    ctx = get_slack_context()
    client = ctx.get("client")

    if client:
        return client

    # Try to create a new client
    try:
        return SlackClient()
    except ValueError as e:
        return None, str(e)
    except ImportError as e:
        return None, str(e)


def get_slack_thread_context(
    channel: str | None = None,
    thread_ts: str | None = None,
    limit: int = 50,
) -> str:
    """
    Get Slack thread context for injection into agent prompts.

    Args:
        channel: Channel to read from
        thread_ts: Thread timestamp to read
        limit: Maximum messages to return

    Returns:
        Formatted context string for prompt injection
    """
    result = _get_slack_client()
    if isinstance(result, tuple):
        return f"Slack: Not available - {result[1]}"

    client = result
    ctx = get_slack_context()
    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")
    ts = thread_ts or ctx.get("thread_ts")

    try:
        if ts:
            messages = client.get_thread_replies(channel=ch, thread_ts=ts, limit=limit)
            context = f"=== Slack Thread ({len(messages)} messages) ===\n\n"
        else:
            messages = client.get_channel_history(channel=ch, limit=limit)
            context = f"=== Recent Slack Messages ({ch}) ===\n\n"

        if not messages:
            return "Slack: No messages found"

        for msg in messages:
            user = msg.user or "bot"
            ts_str = msg.timestamp.strftime("%H:%M") if msg.timestamp else ""
            context += f"[{ts_str}] {user}: {msg.text[:300]}\n"

        return context
    except Exception as e:
        return f"Slack: Error - {e}"


async def send_message(
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """
    Post a message to Slack with automatic [RoleName:session_id] prefix.

    Args:
        message: The message text to post
        channel: Channel name or ID (uses context or default if None)
        thread_ts: Thread timestamp to reply in (uses context if None)

    Returns:
        Confirmation with message timestamp
    """
    result = _get_slack_client()
    if isinstance(result, tuple):
        return f"Slack error: {result[1]}"

    client = result
    ctx = get_slack_context()

    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")
    ts = thread_ts or ctx.get("thread_ts")

    # Add [RoleName:session_id] prefix
    from_agent = ctx.get("from_agent")
    session_id = ctx.get("session_id")

    if from_agent and session_id:
        short_session = session_id[:8] if len(session_id) > 8 else session_id
        prefixed_message = f"[{from_agent}:{short_session}] {message}"
    elif from_agent:
        prefixed_message = f"[{from_agent}] {message}"
    else:
        prefixed_message = message

    try:
        result = client.post_message(channel=ch, text=prefixed_message, thread_ts=ts)
        return f"Posted to {ch} at {result.ts}"
    except Exception as e:
        return f"Error posting to Slack: {e}"


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
    result = _get_slack_client()
    if isinstance(result, tuple):
        return f"Slack error: {result[1]}"

    client = result
    ctx = get_slack_context()
    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")

    try:
        messages = client.get_channel_history(channel=ch, limit=limit)

        if not messages:
            return f"No messages found in {ch}"

        output = f"=== Last {len(messages)} messages from {ch} ===\n\n"
        for msg in messages:
            user = msg.user or "bot"
            ts = msg.timestamp.strftime("%H:%M") if msg.timestamp else ""
            output += f"[{ts}] {user}: {msg.text[:200]}\n"

        return output
    except Exception as e:
        return f"Error reading channel: {e}"


async def read_slack_thread(
    thread_ts: str,
    channel: str | None = None,
    limit: int = 50,
) -> str:
    """
    Read messages from a Slack thread.

    Args:
        thread_ts: Thread parent timestamp
        channel: Channel name or ID (uses context if None)
        limit: Maximum messages to return (default: 50)

    Returns:
        Formatted string with thread messages
    """
    result = _get_slack_client()
    if isinstance(result, tuple):
        return f"Slack error: {result[1]}"

    client = result
    ctx = get_slack_context()
    ch = channel or ctx.get("channel") or os.getenv("SLACK_CHANNEL", "#ai-team")

    try:
        messages = client.get_thread_replies(channel=ch, thread_ts=thread_ts, limit=limit)

        if not messages:
            return "No messages found in thread"

        output = f"=== Thread ({len(messages)} messages) ===\n\n"
        for msg in messages:
            user = msg.user or "bot"
            ts = msg.timestamp.strftime("%H:%M") if msg.timestamp else ""
            output += f"[{ts}] {user}: {msg.text[:300]}\n"

        return output
    except Exception as e:
        return f"Error reading thread: {e}"


# ==============================================================================
# Sync versions (for CrewAI and OpenHands)
# ==============================================================================


def send_message_sync(
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """Synchronous version of send_message."""
    import asyncio

    return asyncio.run(send_message(message, channel, thread_ts))


def read_slack_channel_sync(channel: str | None = None, limit: int = 10) -> str:
    """Synchronous version of read_slack_channel."""
    import asyncio

    return asyncio.run(read_slack_channel(channel, limit))


def read_slack_thread_sync(
    thread_ts: str,
    channel: str | None = None,
    limit: int = 50,
) -> str:
    """Synchronous version of read_slack_thread."""
    import asyncio

    return asyncio.run(read_slack_thread(thread_ts, channel, limit))


# Aliases for backward compatibility
post_slack_message = send_message
post_slack_message_sync = send_message_sync


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
- @SupportEngineer - for customer communication, error investigation with Sentry
- @MarketingManager - for announcements and content
- @ProductManager - for requirements and prioritization

Example: "I've analyzed the request. @SoftwareEngineer please implement the login validation fix."

The mentioned agent will automatically pick up the conversation.
Always provide clear context when handing off so the receiving agent
can understand and work on the task effectively.
"""


def _get_agent_display_name(agent_key: str) -> str:
    """Get display name for an agent key."""
    display_names = {
        "swe": "SoftwareEngineer",
        "release": "ReleaseEngineer",
        "support": "SupportEngineer",
        "pm": "ProductManager",
        "marketer": "MarketingManager",
        "supervisor": "ProductManager",
    }
    return display_names.get(agent_key.lower(), agent_key)


# ==============================================================================
# Backward compatibility aliases
# ==============================================================================

# Alias for backward compatibility with __init__.py
get_slack_context_for_injection = get_slack_thread_context


async def mention_agent(
    agent_name: str,
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """
    Mention another agent with a message.

    This posts a message that includes an @mention of the specified agent,
    which triggers the router to route the conversation to that agent.

    Args:
        agent_name: Agent to mention (e.g., "SoftwareEngineer")
        message: Message to send with the mention
        channel: Channel name or ID (uses context if None)
        thread_ts: Thread timestamp (uses context if None)

    Returns:
        Confirmation with message timestamp
    """
    full_message = f"@{agent_name} {message}"
    return await send_message(full_message, channel, thread_ts)


def mention_agent_sync(
    agent_name: str,
    message: str,
    channel: str | None = None,
    thread_ts: str | None = None,
) -> str:
    """Synchronous version of mention_agent."""
    import asyncio

    return asyncio.run(mention_agent(agent_name, message, channel, thread_ts))
