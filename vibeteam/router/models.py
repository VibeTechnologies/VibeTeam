"""
Data models for the message router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# Re-export from the single source of truth
from agents.shared.role_resolver import (
    ROLE_DISPLAY_NAMES,
    ROLE_MENTION_MAP,
    AgentRole,
    route_by_keywords,
)

__all__ = [
    "AgentRole",
    "ROLE_MENTION_MAP",
    "ROLE_DISPLAY_NAMES",
    "MessageSource",
    "UnifiedMessage",
    "ThreadSubscription",
    "route_by_keywords",
]

# Message sources
MessageSource = Literal[
    "slack",
    "discord",
    "github_issue",
    "github_pr",
    "sentry",
    "gmail",
]


@dataclass
class UnifiedMessage:
    """
    Normalized message format from any source.

    All incoming messages (Slack, Discord, GitHub, etc.) are converted
    to this format before routing.
    """

    source: MessageSource
    thread_id: str  # Unique identifier for the thread/conversation
    channel_id: str  # Channel/room where message was sent
    content: str  # Message text content
    author_id: str  # User ID of message author
    author_name: str  # Display name of author
    is_bot: bool = False  # True if message is from our bot
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Optional fields for different sources
    message_id: str | None = None  # Platform-specific message ID
    reply_to: str | None = None  # Parent message ID if this is a reply
    attachments: list[str] = field(default_factory=list)  # URLs of attachments

    def __post_init__(self):
        """Validate required fields."""
        if not self.thread_id:
            raise ValueError("thread_id is required")
        if not self.channel_id:
            raise ValueError("channel_id is required")


@dataclass
class ThreadSubscription:
    """
    Tracks which agents are subscribed to which threads.

    When a user mentions /SoftwareEngineer in a thread, the router
    subscribes that agent to the thread. All subsequent messages
    in the thread are forwarded to subscribed agents.
    """

    source: MessageSource
    thread_id: str
    agent_role: AgentRole
    session_id: str  # UUID linking to agent session
    subscribed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def key(self) -> str:
        """Unique key for this subscription."""
        return f"{self.source}:{self.thread_id}:{self.agent_role}"


# ROLE_MENTION_MAP and ROLE_DISPLAY_NAMES are imported from agents.shared.role_resolver
# and re-exported above for backward compatibility.
