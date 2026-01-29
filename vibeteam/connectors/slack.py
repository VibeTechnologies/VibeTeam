"""
Slack Connector - API integration for Slack messaging.

Provides functionality to:
- Send messages to channels
- Reply in threads
- Read channel history
- List channels
- React to messages

API Docs: https://api.slack.com/methods
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

# Slack API base URL
SLACK_API_BASE = "https://slack.com/api"

# Default channel for agent updates
DEFAULT_CHANNEL = os.environ.get("SLACK_CHANNEL", "#ai-team")


@dataclass
class SlackMessage:
    """Represents a Slack message."""

    ts: str  # Timestamp (used as message ID)
    text: str
    user: str
    channel: str
    thread_ts: str | None
    reactions: list[str]
    timestamp: datetime

    @property
    def is_thread_reply(self) -> bool:
        """Check if this message is a thread reply."""
        return self.thread_ts is not None and self.thread_ts != self.ts


@dataclass
class SlackChannel:
    """Represents a Slack channel."""

    id: str
    name: str
    is_private: bool
    is_member: bool
    topic: str
    purpose: str


class SlackConnector:
    """
    Slack API connector for messaging.

    Usage:
        connector = SlackConnector()

        # Send message
        connector.send_message("#ai-team", "Hello from VibeTeam!")

        # Reply in thread
        connector.send_message("#ai-team", "Thread reply", thread_ts="1234567890.123456")

        # Get channel history
        messages = connector.get_channel_history("#ai-team", limit=10)

        # React to message
        connector.add_reaction("#ai-team", "1234567890.123456", "thumbsup")
    """

    def __init__(self, bot_token: str | None = None):
        """
        Initialize Slack connector.

        Args:
            bot_token: Slack Bot OAuth token (xoxb-...).
                      If not provided, uses SLACK_BOT_TOKEN env var.
        """
        self.bot_token = (
            bot_token if bot_token is not None else os.environ.get("SLACK_BOT_TOKEN", "")
        )
        self._client: httpx.Client | None = None
        self._channel_cache: dict[str, str] = {}  # name -> id mapping

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=SLACK_API_BASE,
                headers={
                    "Authorization": f"Bearer {self.bot_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def _check_response(self, response: httpx.Response, method: str) -> dict[str, Any]:
        """Check Slack API response and raise on error."""
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise SlackAPIError(f"Slack API error in {method}: {error}")
        return data

    def _resolve_channel_id(self, channel: str) -> str:
        """
        Resolve channel name to channel ID.

        Args:
            channel: Channel name (with or without #) or channel ID

        Returns:
            Channel ID (C...)
        """
        # Already a channel ID
        if channel.startswith("C") or channel.startswith("D"):
            return channel

        # Remove # prefix if present
        channel_name = channel.lstrip("#")

        # Check cache
        if channel_name in self._channel_cache:
            return self._channel_cache[channel_name]

        # Fetch from API
        channels = self.list_channels()
        for ch in channels:
            self._channel_cache[ch.name] = ch.id
            if ch.name == channel_name:
                return ch.id

        raise SlackAPIError(f"Channel not found: {channel}")

    def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> SlackMessage:
        """
        Send a message to a Slack channel.

        Args:
            channel: Channel name (#channel) or ID
            text: Message text (supports Slack markdown)
            thread_ts: Thread timestamp to reply in
            blocks: Optional Block Kit blocks for rich formatting

        Returns:
            SlackMessage with the sent message details
        """
        if not self.bot_token:
            raise SlackAPIError("SLACK_BOT_TOKEN not configured")

        channel_id = self._resolve_channel_id(channel)

        payload: dict[str, Any] = {
            "channel": channel_id,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks

        response = self.client.post("/chat.postMessage", json=payload)
        data = self._check_response(response, "chat.postMessage")

        return SlackMessage(
            ts=data["ts"],
            text=text,
            user=data.get("message", {}).get("user", "bot"),
            channel=channel_id,
            thread_ts=thread_ts,
            reactions=[],
            timestamp=datetime.now(),
        )

    def update_message(
        self,
        channel: str,
        ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> SlackMessage:
        """
        Update an existing message.

        Args:
            channel: Channel name or ID
            ts: Timestamp of message to update
            text: New message text
            blocks: Optional Block Kit blocks

        Returns:
            Updated SlackMessage
        """
        channel_id = self._resolve_channel_id(channel)

        payload: dict[str, Any] = {
            "channel": channel_id,
            "ts": ts,
            "text": text,
        }
        if blocks:
            payload["blocks"] = blocks

        response = self.client.post("/chat.update", json=payload)
        data = self._check_response(response, "chat.update")

        return SlackMessage(
            ts=data["ts"],
            text=text,
            user=data.get("message", {}).get("user", "bot"),
            channel=channel_id,
            thread_ts=None,
            reactions=[],
            timestamp=datetime.now(),
        )

    def delete_message(self, channel: str, ts: str) -> bool:
        """
        Delete a message.

        Args:
            channel: Channel name or ID
            ts: Timestamp of message to delete

        Returns:
            True if deleted successfully
        """
        channel_id = self._resolve_channel_id(channel)

        response = self.client.post(
            "/chat.delete",
            json={"channel": channel_id, "ts": ts},
        )
        self._check_response(response, "chat.delete")
        return True

    def add_reaction(self, channel: str, ts: str, emoji: str) -> bool:
        """
        Add a reaction to a message.

        Args:
            channel: Channel name or ID
            ts: Timestamp of message to react to
            emoji: Emoji name (without colons)

        Returns:
            True if reaction added successfully
        """
        channel_id = self._resolve_channel_id(channel)

        response = self.client.post(
            "/reactions.add",
            json={
                "channel": channel_id,
                "timestamp": ts,
                "name": emoji,
            },
        )
        data = response.json()
        # Ignore "already_reacted" error
        if not data.get("ok") and data.get("error") != "already_reacted":
            raise SlackAPIError(f"Failed to add reaction: {data.get('error')}")
        return True

    def get_channel_history(
        self,
        channel: str,
        limit: int = 20,
        oldest: str | None = None,
        latest: str | None = None,
    ) -> list[SlackMessage]:
        """
        Get message history from a channel.

        Args:
            channel: Channel name or ID
            limit: Max number of messages to return
            oldest: Only messages after this timestamp
            latest: Only messages before this timestamp

        Returns:
            List of SlackMessage objects (newest first)
        """
        channel_id = self._resolve_channel_id(channel)

        params: dict[str, Any] = {
            "channel": channel_id,
            "limit": limit,
        }
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest

        response = self.client.get("/conversations.history", params=params)
        data = self._check_response(response, "conversations.history")

        messages = []
        for msg in data.get("messages", []):
            messages.append(
                SlackMessage(
                    ts=msg["ts"],
                    text=msg.get("text", ""),
                    user=msg.get("user", msg.get("bot_id", "unknown")),
                    channel=channel_id,
                    thread_ts=msg.get("thread_ts"),
                    reactions=[r["name"] for r in msg.get("reactions", [])],
                    timestamp=datetime.fromtimestamp(float(msg["ts"])),
                )
            )
        return messages

    def get_thread_replies(
        self,
        channel: str,
        thread_ts: str,
        limit: int = 50,
    ) -> list[SlackMessage]:
        """
        Get replies in a thread.

        Args:
            channel: Channel name or ID
            thread_ts: Thread parent timestamp
            limit: Max number of replies

        Returns:
            List of SlackMessage objects
        """
        channel_id = self._resolve_channel_id(channel)

        response = self.client.get(
            "/conversations.replies",
            params={
                "channel": channel_id,
                "ts": thread_ts,
                "limit": limit,
            },
        )
        data = self._check_response(response, "conversations.replies")

        messages = []
        for msg in data.get("messages", []):
            messages.append(
                SlackMessage(
                    ts=msg["ts"],
                    text=msg.get("text", ""),
                    user=msg.get("user", msg.get("bot_id", "unknown")),
                    channel=channel_id,
                    thread_ts=msg.get("thread_ts"),
                    reactions=[r["name"] for r in msg.get("reactions", [])],
                    timestamp=datetime.fromtimestamp(float(msg["ts"])),
                )
            )
        return messages

    def list_channels(self, include_private: bool = False) -> list[SlackChannel]:
        """
        List channels the bot can access.

        Args:
            include_private: Include private channels

        Returns:
            List of SlackChannel objects
        """
        types = "public_channel"
        if include_private:
            types += ",private_channel"

        response = self.client.get(
            "/conversations.list",
            params={
                "types": types,
                "exclude_archived": True,
                "limit": 200,
            },
        )
        data = self._check_response(response, "conversations.list")

        channels = []
        for ch in data.get("channels", []):
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

    def get_channel_by_name(self, name: str) -> SlackChannel | None:
        """
        Get channel by name.

        Args:
            name: Channel name (with or without #)

        Returns:
            SlackChannel or None if not found
        """
        name = name.lstrip("#")
        channels = self.list_channels(include_private=True)
        for ch in channels:
            if ch.name == name:
                return ch
        return None

    def post_status_update(
        self,
        text: str,
        channel: str | None = None,
        thread_ts: str | None = None,
    ) -> SlackMessage:
        """
        Post a status update to the default AI team channel.

        Args:
            text: Status message
            channel: Optional channel override
            thread_ts: Optional thread to reply in

        Returns:
            SlackMessage with sent message details
        """
        target_channel = channel or DEFAULT_CHANNEL
        return self.send_message(target_channel, text, thread_ts=thread_ts)

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "SlackConnector":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class SlackAPIError(Exception):
    """Raised when Slack API returns an error."""

    pass
