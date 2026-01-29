"""
Slack Connector - API integration for Slack messaging.

Provides functionality to:
- Post messages to channels
- Read channel history
- Handle @mentions
- Thread replies
- List channels

Uses slack-bolt for event handling and slack-sdk for API calls.

API Docs: https://api.slack.com/methods
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


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


# Agent name to Slack user ID mapping
# This will be populated from environment or config
AGENT_USER_MAP: dict[str, str] = {}


class SlackConnector:
    """
    Slack API connector for messaging.

    Usage:
        connector = SlackConnector()

        # Post message
        connector.post_message("#ai-team", "Hello from PM agent!")

        # Read channel history
        messages = connector.get_channel_history("#ai-team", limit=10)

        # Reply in thread
        connector.post_message("#ai-team", "Following up...", thread_ts=msg.ts)

        # @mention another agent
        connector.mention_agent("#ai-team", "swe", "Can you review this PR?")
    """

    def __init__(
        self,
        token: str | None = None,
        default_channel: str | None = None,
    ):
        """
        Initialize Slack connector.

        Args:
            token: Slack bot token (or from SLACK_BOT_TOKEN env)
            default_channel: Default channel for messages
        """
        self.token = token or os.environ.get("SLACK_BOT_TOKEN")
        self.default_channel = default_channel or os.environ.get(
            "SLACK_DEFAULT_CHANNEL", "#ai-team"
        )

        if not self.token:
            raise ValueError("Slack token required. Set SLACK_BOT_TOKEN env var or pass token.")

        self.client = WebClient(token=self.token)
        self._bot_user_id: str | None = None
        self._channel_cache: dict[str, str] = {}  # name -> id

        # Load agent user mappings from env
        self._load_agent_mappings()

    def _load_agent_mappings(self) -> None:
        """Load agent-to-Slack-user mappings from environment."""
        global AGENT_USER_MAP
        # Format: SLACK_AGENT_PM=U12345,SLACK_AGENT_SWE=U67890
        for key, value in os.environ.items():
            if key.startswith("SLACK_AGENT_"):
                agent_name = key.replace("SLACK_AGENT_", "").lower()
                AGENT_USER_MAP[agent_name] = value

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
        except SlackApiError:
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

    # =====================
    # Message Operations
    # =====================

    def post_message(
        self,
        channel: str | None = None,
        text: str = "",
        thread_ts: str | None = None,
        blocks: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> SlackMessage:
        """
        Post a message to a channel.

        Args:
            channel: Channel name or ID (uses default if None)
            text: Message text
            thread_ts: Thread timestamp to reply to
            blocks: Block Kit blocks for rich formatting
            metadata: Message metadata for tracking

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
        if metadata:
            kwargs["metadata"] = metadata

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

    # =====================
    # Agent Mention Operations
    # =====================

    def mention_agent(
        self,
        channel: str,
        agent_key: str,
        message: str,
        thread_ts: str | None = None,
    ) -> SlackMessage:
        """
        Mention another agent in a message.

        Args:
            channel: Channel to post in
            agent_key: Agent key (pm, swe, release, support, sre, marketer)
            message: Message content
            thread_ts: Thread to reply in

        Returns:
            The posted message
        """
        agent_id = AGENT_USER_MAP.get(agent_key.lower())
        if agent_id:
            text = f"<@{agent_id}> {message}"
        else:
            # Fallback to plain text mention
            text = f"@{agent_key}: {message}"

        return self.post_message(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
        )

    def is_mention_for_agent(self, message: SlackMessage, agent_key: str) -> bool:
        """
        Check if a message mentions a specific agent.

        When a specific agent Slack user ID is configured via SLACK_AGENT_{KEY},
        it checks for that user. Otherwise, it checks if the bot itself is mentioned
        (for single-bot deployments where one bot handles all agents).

        Args:
            message: The message to check
            agent_key: Agent key to check for

        Returns:
            True if the agent is mentioned
        """
        agent_id = AGENT_USER_MAP.get(agent_key.lower())
        if agent_id:
            return agent_id in message.mentions

        # Fallback 1: check for @agent_key pattern (e.g., "@support help me")
        if f"@{agent_key}" in message.text.lower():
            return True

        # Fallback 2: if no agent-specific user configured, respond to bot mentions
        # This enables single-bot deployments where all agents share one bot user
        if self.bot_user_id in message.mentions:
            return True

        return False

    def extract_mentioned_agents(self, message: SlackMessage) -> list[str]:
        """
        Extract all agent keys mentioned in a message.

        Args:
            message: The message to parse

        Returns:
            List of agent keys that were mentioned
        """
        mentioned = []
        for agent_key, user_id in AGENT_USER_MAP.items():
            if user_id in message.mentions:
                mentioned.append(agent_key)

        # Also check for text-based mentions (@pm, @swe, etc.)
        text_lower = message.text.lower()
        for agent_key in ["pm", "swe", "release", "support", "sre", "marketer", "supervisor"]:
            if f"@{agent_key}" in text_lower and agent_key not in mentioned:
                mentioned.append(agent_key)

        return mentioned

    # =====================
    # Channel Operations
    # =====================

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

    def join_channel(self, channel: str) -> bool:
        """
        Join a channel.

        Args:
            channel: Channel name or ID

        Returns:
            True if joined successfully
        """
        try:
            channel_id = self._resolve_channel(channel)
            self.client.conversations_join(channel=channel_id)
            return True
        except SlackApiError:
            return False

    # =====================
    # User Operations
    # =====================

    def get_user_info(self, user_id: str) -> dict:
        """
        Get information about a user.

        Args:
            user_id: Slack user ID

        Returns:
            User information dict
        """
        response = self.client.users_info(user=user_id)
        user = response.get("user", {})
        return {
            "id": user.get("id"),
            "name": user.get("name"),
            "real_name": user.get("real_name"),
            "is_bot": user.get("is_bot", False),
        }

    def get_display_name(self, user_id: str) -> str:
        """
        Get a user's display name.

        Args:
            user_id: Slack user ID

        Returns:
            Display name or "Unknown"
        """
        try:
            info = self.get_user_info(user_id)
            return info.get("real_name") or info.get("name") or "Unknown"
        except SlackApiError:
            return "Unknown"

    # =====================
    # Utility Methods
    # =====================

    def format_agent_message(
        self,
        agent_name: str,
        message: str,
        include_emoji: bool = True,
    ) -> str:
        """
        Format a message from an agent with consistent styling.

        Args:
            agent_name: Name of the agent (Curie, Turing, etc.)
            message: Message content
            include_emoji: Include role-specific emoji

        Returns:
            Formatted message
        """
        emojis = {
            "curie": ":chart_with_upwards_trend:",  # PM
            "turing": ":computer:",  # SWE
            "einstein": ":rocket:",  # Release
            "darwin": ":headphones:",  # Support
            "newton": ":shield:",  # SRE
            "ada": ":mega:",  # Marketer
        }

        emoji = ""
        if include_emoji:
            emoji = emojis.get(agent_name.lower(), ":robot_face:") + " "

        return f"{emoji}*[{agent_name}]* {message}"


def cli_test_connection() -> None:
    """CLI helper to test Slack connection."""
    try:
        connector = SlackConnector()
        print(f"Connected as bot user: {connector.bot_user_id}")

        channels = connector.list_channels()
        print(f"\nAccessible channels ({len(channels)}):")
        for ch in channels[:5]:
            member = "[MEMBER]" if ch.is_member else ""
            print(f"  #{ch.name} {member}")

    except ValueError as e:
        print(f"Error: {e}")
        print("Set SLACK_BOT_TOKEN environment variable.")


if __name__ == "__main__":
    cli_test_connection()
