"""Simulated channel for testing multi-agent conversations.

This module provides an in-memory simulation of Discord/Slack channels
for testing multi-agent conversations without real API calls.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class ChannelMessage:
    """A message in the simulated channel."""

    id: str
    author: str  # Agent role or "user" or "system"
    content: str
    timestamp: datetime
    mentions: list[str] = field(default_factory=list)
    reply_to: str | None = None
    metadata: dict = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "author": self.author,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "mentions": self.mentions,
            "reply_to": self.reply_to,
            "metadata": self.metadata,
            "tool_calls": self.tool_calls,
        }


@dataclass
class SimulatedChannel:
    """
    In-memory simulation of a Discord/Slack channel.

    Used for testing multi-agent conversations without real API calls.
    Supports:
    - Message posting and history
    - Mention extraction
    - Listener subscriptions for reactive agents
    - Transcript generation
    - DeepEval Turn conversion
    """

    name: str
    messages: list[ChannelMessage] = field(default_factory=list)
    listeners: list[Callable[[ChannelMessage], Awaitable[None]]] = field(default_factory=list)
    _message_counter: int = 0

    def post(
        self,
        author: str,
        content: str,
        mentions: list[str] | None = None,
        reply_to: str | None = None,
        metadata: dict | None = None,
        tool_calls: list[dict] | None = None,
    ) -> ChannelMessage:
        """Post a message to the channel.

        Args:
            author: The author of the message (agent role, "user", or "system")
            content: The message content
            mentions: Explicit mentions (if None, extracted from content)
            reply_to: ID of message being replied to
            metadata: Additional metadata
            tool_calls: Tool calls made by the agent

        Returns:
            The created ChannelMessage
        """
        self._message_counter += 1
        msg = ChannelMessage(
            id=f"msg_{self._message_counter:04d}",
            author=author,
            content=content,
            timestamp=datetime.now(timezone.utc),
            mentions=mentions if mentions is not None else self._extract_mentions(content),
            reply_to=reply_to,
            metadata=metadata or {},
            tool_calls=tool_calls or [],
        )
        self.messages.append(msg)

        # Notify listeners (agents watching the channel)
        for listener in self.listeners:
            asyncio.create_task(listener(msg))

        return msg

    def _extract_mentions(self, content: str) -> list[str]:
        """Extract @mentions from message content.

        Handles various mention formats:
        - @SoftwareEngineer
        - @software_engineer
        - @ReleaseEngineer
        """
        # Match @word patterns (with underscores allowed)
        return re.findall(r"@(\w+)", content)

    def get_history(self, limit: int = 50) -> list[ChannelMessage]:
        """Get recent messages.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of recent messages (most recent last)
        """
        return self.messages[-limit:]

    def get_messages_by_author(self, author: str) -> list[ChannelMessage]:
        """Get all messages from a specific author.

        Args:
            author: The author to filter by

        Returns:
            List of messages from that author
        """
        return [m for m in self.messages if m.author == author]

    def get_messages_since(self, message_id: str) -> list[ChannelMessage]:
        """Get all messages since a given message ID.

        Args:
            message_id: The message ID to start from (exclusive)

        Returns:
            List of messages after the given ID
        """
        found = False
        result = []
        for msg in self.messages:
            if found:
                result.append(msg)
            elif msg.id == message_id:
                found = True
        return result

    def subscribe(self, callback: Callable[[ChannelMessage], Awaitable[None]]) -> None:
        """Subscribe to new messages.

        Args:
            callback: Async function to call when a new message is posted
        """
        self.listeners.append(callback)

    def unsubscribe(self, callback: Callable[[ChannelMessage], Awaitable[None]]) -> None:
        """Unsubscribe from new messages.

        Args:
            callback: The callback to remove
        """
        if callback in self.listeners:
            self.listeners.remove(callback)

    def clear(self) -> None:
        """Clear all messages and reset counter."""
        self.messages.clear()
        self._message_counter = 0

    def to_transcript(self) -> str:
        """Generate human-readable transcript.

        Returns:
            Formatted transcript string
        """
        lines = []
        for msg in self.messages:
            reply = f" (replying to {msg.reply_to})" if msg.reply_to else ""
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            lines.append(f"[{timestamp}] {msg.author}{reply}: {msg.content}")
        return "\n".join(lines)

    def to_deepeval_turns(self) -> list:
        """Convert to DeepEval Turn objects for evaluation.

        Returns:
            List of Turn objects for ConversationalTestCase

        Note:
            Requires deepeval to be installed. Import is done inside
            the function to avoid import errors when deepeval is not available.
        """
        try:
            from deepeval.test_case import Turn
        except ImportError:
            raise ImportError(
                "deepeval is required for to_deepeval_turns(). Install with: pip install deepeval"
            ) from None

        turns = []
        for msg in self.messages:
            # Map author to role (user stays user, all agents are assistant)
            role = "user" if msg.author == "user" else "assistant"

            # Include author in content for multi-agent clarity
            content = f"[{msg.author}]: {msg.content}"

            # Create Turn (ToolCall conversion if tool_calls present)
            turn_kwargs = {"role": role, "content": content}

            if msg.tool_calls:
                try:
                    from deepeval.test_case import ToolCall

                    turn_kwargs["tools_called"] = [
                        ToolCall(
                            name=tc.get("name", "unknown"),
                            input=tc.get("input", {}),
                            output=tc.get("output", ""),
                        )
                        for tc in msg.tool_calls
                    ]
                except ImportError:
                    pass  # ToolCall not available in this version

            turns.append(Turn(**turn_kwargs))

        return turns

    def __len__(self) -> int:
        """Return number of messages."""
        return len(self.messages)

    def __repr__(self) -> str:
        """String representation."""
        return f"SimulatedChannel(name={self.name!r}, messages={len(self.messages)})"
