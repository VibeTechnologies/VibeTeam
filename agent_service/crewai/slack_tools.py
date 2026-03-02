"""
CrewAI-specific Slack tool wrappers using BaseTool.

These wrap the shared async slack_tools functions for use with CrewAI agents.
All tools use the sync versions since CrewAI runs synchronously.

Note: Transfer tools have been removed. Agents now use natural @mentions
in their responses for handoffs (e.g., "@SoftwareEngineer please fix this bug").
The bot parses these mentions and routes to the appropriate agent session.
"""

from pydantic import BaseModel, Field

try:
    from crewai.tools import BaseTool

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    BaseTool = object


# =============================================================================
# Pydantic Input Schemas
# =============================================================================


class PostMessageInput(BaseModel):
    """Input schema for posting a Slack message."""

    message: str = Field(..., description="The message text to post")
    channel: str = Field(default="", description="Channel to post to (optional, uses default)")


class ReadChannelInput(BaseModel):
    """Input schema for reading Slack channel."""

    limit: int = Field(default=10, description="Maximum messages to return")


class ReadThreadInput(BaseModel):
    """Input schema for reading Slack thread."""

    thread_ts: str = Field(..., description="Thread parent timestamp")
    limit: int = Field(default=50, description="Maximum messages to return")


class MentionAgentInput(BaseModel):
    """Input schema for mentioning an agent."""

    agent_key: str = Field(
        ..., description="Agent to mention: swe, sre, release, support, pm, marketer"
    )
    message: str = Field(..., description="Message explaining the task")


# =============================================================================
# Core Slack Tools
# =============================================================================


class PostSlackMessageTool(BaseTool if CREWAI_AVAILABLE else object):
    """Post a message to Slack."""

    name: str = "post_slack_message"
    description: str = "Post a message to the Slack channel for team visibility."
    args_schema: type[BaseModel] = PostMessageInput

    def _run(self, message: str, channel: str = "") -> str:
        from agent_service.shared.slack_tools import post_slack_message_sync

        return post_slack_message_sync(message, channel if channel else None)


class ReadSlackChannelTool(BaseTool if CREWAI_AVAILABLE else object):
    """Read recent Slack messages."""

    name: str = "read_slack_channel"
    description: str = "Read recent messages from the Slack channel."
    args_schema: type[BaseModel] = ReadChannelInput

    def _run(self, limit: int = 10) -> str:
        from agent_service.shared.slack_tools import read_slack_channel_sync

        return read_slack_channel_sync(limit=limit)


class ReadSlackThreadTool(BaseTool if CREWAI_AVAILABLE else object):
    """Read messages from a Slack thread."""

    name: str = "read_slack_thread"
    description: str = "Read messages from a specific Slack thread."
    args_schema: type[BaseModel] = ReadThreadInput

    def _run(self, thread_ts: str, limit: int = 50) -> str:
        from agent_service.shared.slack_tools import read_slack_thread_sync

        return read_slack_thread_sync(thread_ts, limit=limit)


class MentionAgentTool(BaseTool if CREWAI_AVAILABLE else object):
    """Mention another agent in Slack."""

    name: str = "mention_agent"
    description: str = (
        "Mention another agent in Slack to get their attention. "
        "Use agent_key: swe, sre, release, support, pm, or marketer."
    )
    args_schema: type[BaseModel] = MentionAgentInput

    def _run(self, agent_key: str, message: str) -> str:
        from agent_service.shared.slack_tools import mention_agent_sync

        return mention_agent_sync(agent_key, message)


# =============================================================================
# Factory Functions
# =============================================================================


def get_slack_tools() -> list:
    """Get all Slack communication tools for an agent."""
    return [
        PostSlackMessageTool(),
        ReadSlackChannelTool(),
        ReadSlackThreadTool(),
        MentionAgentTool(),
    ]
