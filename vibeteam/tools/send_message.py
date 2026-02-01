"""
SendMessage Tool - OpenHands tool wrapper for posting messages to Slack/Discord.

Provides agent-callable functions for sending messages to channels/threads.
This enables agents to communicate with users and other agents.
"""

from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult


class SendMessageTool(BaseTool):
    """
    Tool for sending messages to Slack or Discord channels/threads.

    Wraps SlackConnector and DiscordConnector for use by VibeTeam agents.
    The platform is determined by the connector passed at initialization.
    """

    name = "send_message"
    description = "Send a message to a Slack/Discord channel or thread"

    def __init__(
        self,
        slack_connector=None,
        discord_connector=None,
        default_channel: str | None = None,
    ):
        """
        Initialize SendMessage tool.

        Args:
            slack_connector: SlackConnector instance (optional)
            discord_connector: DiscordConnector instance (optional)
            default_channel: Default channel to post to
        """
        self.slack = slack_connector
        self.discord = discord_connector
        self.default_channel = default_channel

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
                        "platform": {
                            "type": "string",
                            "enum": ["slack", "discord"],
                            "description": "Target platform (slack or discord)",
                        },
                        "channel": {
                            "type": "string",
                            "description": "Channel name or ID (e.g., #general, C0123456)",
                        },
                        "message": {
                            "type": "string",
                            "description": "Message text to send. Include @RoleName to hand off to another agent.",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Thread timestamp/ID to reply in (optional)",
                        },
                    },
                    "required": ["message"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Send a message to the specified channel/thread.

        Args:
            platform: Target platform (slack or discord)
            channel: Channel name or ID
            message: Message text
            thread_id: Thread ID for replies (optional)

        Returns:
            ToolResult with success/failure status
        """
        platform = kwargs.get("platform", "slack")
        channel = kwargs.get("channel", self.default_channel)
        message = kwargs.get("message", "")
        thread_id = kwargs.get("thread_id")

        if not message:
            return ToolResult(success=False, output="", error="message is required")

        try:
            if platform == "slack":
                return await self._send_slack(channel, message, thread_id)
            elif platform == "discord":
                return await self._send_discord(channel, message, thread_id)
            else:
                return ToolResult(
                    success=False, output="", error=f"Unknown platform: {platform}"
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def _send_slack(
        self, channel: str | None, message: str, thread_ts: str | None
    ) -> ToolResult:
        """Send message via Slack."""
        if not self.slack:
            return ToolResult(
                success=False,
                output="",
                error="Slack connector not configured",
            )

        if not channel:
            return ToolResult(
                success=False,
                output="",
                error="channel is required for Slack messages",
            )

        try:
            result = self.slack.post_message(
                channel=channel,
                text=message,
                thread_ts=thread_ts,
            )
            return ToolResult(
                success=True,
                output=f"Message sent to {channel}" + (f" (thread: {thread_ts})" if thread_ts else ""),
                metadata={"ts": result.ts, "channel": result.channel},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Slack error: {e}")

    async def _send_discord(
        self, channel: str | None, message: str, thread_id: str | None
    ) -> ToolResult:
        """Send message via Discord."""
        if not self.discord:
            return ToolResult(
                success=False,
                output="",
                error="Discord connector not configured",
            )

        if not channel:
            return ToolResult(
                success=False,
                output="",
                error="channel is required for Discord messages",
            )

        try:
            # Discord connector posts to channels
            # thread_id handling depends on Discord connector implementation
            result = await self.discord.send_message(
                channel_id=channel,
                content=message,
                thread_id=thread_id,
            )
            return ToolResult(
                success=True,
                output=f"Message sent to {channel}" + (f" (thread: {thread_id})" if thread_id else ""),
                metadata={"message_id": result.get("id") if isinstance(result, dict) else str(result)},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Discord error: {e}")
