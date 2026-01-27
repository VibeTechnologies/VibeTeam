"""
Slack Tool - OpenHands tool wrapper for Slack connector.

Provides agent-callable functions for Slack messaging operations.
"""

import json
from dataclasses import asdict
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.slack import SlackConnector


class SlackTool(BaseTool):
    """
    Tool for interacting with Slack channels and messages.

    Wraps the SlackConnector for use by VibeTeam agents.
    Enables agents to:
    - Post messages to channels
    - Read channel history
    - Mention other agents for delegation
    - Reply in threads
    """

    name = "slack"
    description = "Post and read messages in Slack channels, mention team members"

    def __init__(
        self,
        token: str | None = None,
        default_channel: str | None = None,
        agent_name: str | None = None,
    ):
        """
        Initialize Slack tool.

        Args:
            token: Slack bot token (or from SLACK_BOT_TOKEN env)
            default_channel: Default channel for messages
            agent_name: Name of the agent using this tool (for formatted messages)
        """
        self.connector = SlackConnector(token=token, default_channel=default_channel)
        self.agent_name = agent_name

    def get_schema(self) -> dict:
        """Return OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "post_message",
                                "read_channel",
                                "mention_agent",
                                "reply_thread",
                                "list_channels",
                            ],
                            "description": "The Slack action to perform",
                        },
                        "channel": {
                            "type": "string",
                            "description": "Channel name (e.g., #ai-team) or ID",
                        },
                        "message": {
                            "type": "string",
                            "description": "Message text to post",
                        },
                        "agent": {
                            "type": "string",
                            "enum": [
                                "pm",
                                "swe",
                                "release",
                                "support",
                                "sre",
                                "marketer",
                                "supervisor",
                            ],
                            "description": "Agent to mention (for mention_agent action)",
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": "Thread timestamp to reply to",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum messages to return (default 10)",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Slack action."""
        action = kwargs.get("action")
        channel = kwargs.get("channel")

        try:
            if action == "post_message":
                message = kwargs.get("message")
                if not message:
                    return ToolResult(success=False, output="", error="message required")

                # Format message with agent name if available
                if self.agent_name:
                    formatted = self.connector.format_agent_message(self.agent_name, message)
                else:
                    formatted = message

                thread_ts = kwargs.get("thread_ts")
                msg = self.connector.post_message(
                    channel=channel,
                    text=formatted,
                    thread_ts=thread_ts,
                )
                return ToolResult(
                    success=True,
                    output=f"Posted to {channel or self.connector.default_channel}: {message[:50]}...",
                    metadata={"ts": msg.ts, "channel": msg.channel},
                )

            elif action == "read_channel":
                limit = kwargs.get("limit", 10)
                messages = self.connector.get_channel_history(channel, limit=limit)

                # Format messages for agent consumption
                formatted = []
                for msg in messages:
                    display_name = (
                        self.connector.get_display_name(msg.user) if not msg.is_bot else "Bot"
                    )
                    formatted.append(
                        {
                            "ts": msg.ts,
                            "user": display_name,
                            "text": msg.text,
                            "is_bot": msg.is_bot,
                            "mentions": msg.mentions,
                            "thread_ts": msg.thread_ts,
                        }
                    )

                return ToolResult(
                    success=True,
                    output=json.dumps(formatted, indent=2),
                    metadata={"count": len(formatted)},
                )

            elif action == "mention_agent":
                agent = kwargs.get("agent")
                message = kwargs.get("message")
                if not agent or not message:
                    return ToolResult(
                        success=False,
                        output="",
                        error="agent and message required",
                    )

                # Add context from the mentioning agent
                context = ""
                if self.agent_name:
                    context = f"[From {self.agent_name}] "

                thread_ts = kwargs.get("thread_ts")
                msg = self.connector.mention_agent(
                    channel=channel or self.connector.default_channel,
                    agent_key=agent,
                    message=context + message,
                    thread_ts=thread_ts,
                )
                return ToolResult(
                    success=True,
                    output=f"Mentioned @{agent}: {message[:50]}...",
                    metadata={"ts": msg.ts, "mentioned_agent": agent},
                )

            elif action == "reply_thread":
                thread_ts = kwargs.get("thread_ts")
                message = kwargs.get("message")
                if not thread_ts or not message:
                    return ToolResult(
                        success=False,
                        output="",
                        error="thread_ts and message required",
                    )

                # Format message with agent name if available
                if self.agent_name:
                    formatted = self.connector.format_agent_message(self.agent_name, message)
                else:
                    formatted = message

                msg = self.connector.post_message(
                    channel=channel,
                    text=formatted,
                    thread_ts=thread_ts,
                )
                return ToolResult(
                    success=True,
                    output=f"Replied in thread: {message[:50]}...",
                    metadata={"ts": msg.ts, "thread_ts": thread_ts},
                )

            elif action == "list_channels":
                channels = self.connector.list_channels()
                formatted = [
                    {
                        "id": ch.id,
                        "name": ch.name,
                        "is_member": ch.is_member,
                        "topic": ch.topic[:100] if ch.topic else "",
                    }
                    for ch in channels
                ]
                return ToolResult(
                    success=True,
                    output=json.dumps(formatted, indent=2),
                    metadata={"count": len(formatted)},
                )

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class SlackListenerTool(BaseTool):
    """
    Tool for checking incoming Slack messages directed at an agent.

    This tool allows agents to check if they have been mentioned
    and retrieve messages that require their attention.
    """

    name = "slack_inbox"
    description = "Check for Slack messages that mention or require this agent's attention"

    def __init__(
        self,
        token: str | None = None,
        agent_key: str = "supervisor",
        default_channel: str | None = None,
    ):
        """
        Initialize Slack listener tool.

        Args:
            token: Slack bot token
            agent_key: Key for this agent (pm, swe, release, etc.)
            default_channel: Channel to monitor
        """
        self.connector = SlackConnector(token=token, default_channel=default_channel)
        self.agent_key = agent_key

    def get_schema(self) -> dict:
        """Return OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["check_mentions", "get_unread"],
                            "description": "Action to perform",
                        },
                        "channel": {
                            "type": "string",
                            "description": "Channel to check (default: team channel)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max messages to check (default 20)",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Check for messages directed at this agent."""
        action = kwargs.get("action")
        channel = kwargs.get("channel")
        limit = kwargs.get("limit", 20)

        try:
            if action == "check_mentions":
                messages = self.connector.get_channel_history(channel, limit=limit)

                # Filter for messages mentioning this agent
                mentions = []
                for msg in messages:
                    if self.connector.is_mention_for_agent(msg, self.agent_key):
                        mentions.append(
                            {
                                "ts": msg.ts,
                                "user": msg.user,
                                "text": msg.text,
                                "thread_ts": msg.thread_ts,
                            }
                        )

                return ToolResult(
                    success=True,
                    output=json.dumps(mentions, indent=2),
                    metadata={"count": len(mentions), "agent": self.agent_key},
                )

            elif action == "get_unread":
                # Get recent messages (in production, track last-read timestamp)
                messages = self.connector.get_channel_history(channel, limit=limit)

                formatted = []
                for msg in messages:
                    # Skip bot messages unless they mention this agent
                    if msg.is_bot and not self.connector.is_mention_for_agent(msg, self.agent_key):
                        continue

                    mentioned_agents = self.connector.extract_mentioned_agents(msg)
                    formatted.append(
                        {
                            "ts": msg.ts,
                            "user": msg.user,
                            "text": msg.text,
                            "mentions_me": self.agent_key in mentioned_agents,
                            "other_mentions": [a for a in mentioned_agents if a != self.agent_key],
                        }
                    )

                return ToolResult(
                    success=True,
                    output=json.dumps(formatted, indent=2),
                    metadata={"count": len(formatted)},
                )

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
