"""
CrewAI-specific Slack tool wrappers using BaseTool.

These wrap the shared async slack_tools functions for use with CrewAI agents.
All tools use the sync versions since CrewAI runs synchronously.
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


class TransferInput(BaseModel):
    """Input schema for transfer tools."""

    task: str = Field(..., description="Description of the task to hand off")
    context: str = Field(
        default="", description="Additional context (error logs, requirements, etc.)"
    )


# =============================================================================
# Core Slack Tools
# =============================================================================


class PostSlackMessageTool(BaseTool if CREWAI_AVAILABLE else object):
    """Post a message to Slack."""

    name: str = "post_slack_message"
    description: str = "Post a message to the Slack channel for team visibility."
    args_schema: type[BaseModel] = PostMessageInput

    def _run(self, message: str, channel: str = "") -> str:
        from agents.shared.slack_tools import post_slack_message_sync

        return post_slack_message_sync(message, channel if channel else None)


class ReadSlackChannelTool(BaseTool if CREWAI_AVAILABLE else object):
    """Read recent Slack messages."""

    name: str = "read_slack_channel"
    description: str = "Read recent messages from the Slack channel."
    args_schema: type[BaseModel] = ReadChannelInput

    def _run(self, limit: int = 10) -> str:
        from agents.shared.slack_tools import read_slack_channel_sync

        return read_slack_channel_sync(limit=limit)


class ReadSlackThreadTool(BaseTool if CREWAI_AVAILABLE else object):
    """Read messages from a Slack thread."""

    name: str = "read_slack_thread"
    description: str = "Read messages from a specific Slack thread."
    args_schema: type[BaseModel] = ReadThreadInput

    def _run(self, thread_ts: str, limit: int = 50) -> str:
        from agents.shared.slack_tools import read_slack_thread_sync

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
        from agents.shared.slack_tools import mention_agent_sync

        return mention_agent_sync(agent_key, message)


# =============================================================================
# Transfer Tools
# =============================================================================


class TransferToSWETool(BaseTool if CREWAI_AVAILABLE else object):
    """Transfer a task to SoftwareEngineer."""

    name: str = "transfer_to_swe"
    description: str = (
        "Transfer a coding task to SoftwareEngineer. "
        "Use for bugs, feature implementation, PRs, or code reviews."
    )
    args_schema: type[BaseModel] = TransferInput

    def _run(self, task: str, context: str = "") -> str:
        from agents.shared.slack_tools import transfer_to_swe_sync

        return transfer_to_swe_sync(task, context)


class TransferToSRETool(BaseTool if CREWAI_AVAILABLE else object):
    """Transfer a task to SiteReliabilityEngineer."""

    name: str = "transfer_to_sre"
    description: str = (
        "Transfer an infrastructure task to SiteReliabilityEngineer. "
        "Use for monitoring, Sentry errors, latency, or deployment issues."
    )
    args_schema: type[BaseModel] = TransferInput

    def _run(self, task: str, context: str = "") -> str:
        from agents.shared.slack_tools import transfer_to_sre_sync

        return transfer_to_sre_sync(task, context)


class TransferToReleaseTool(BaseTool if CREWAI_AVAILABLE else object):
    """Transfer a task to ReleaseEngineer."""

    name: str = "transfer_to_release"
    description: str = (
        "Transfer a deployment task to ReleaseEngineer. "
        "Use when code is ready for deployment or releases need to be created."
    )
    args_schema: type[BaseModel] = TransferInput

    def _run(self, task: str, context: str = "") -> str:
        from agents.shared.slack_tools import transfer_to_release_sync

        return transfer_to_release_sync(task, context)


class TransferToSupportTool(BaseTool if CREWAI_AVAILABLE else object):
    """Transfer a task to SupportEngineer."""

    name: str = "transfer_to_support"
    description: str = (
        "Transfer a customer task to SupportEngineer. "
        "Use for customer issues, tickets, or customer communication."
    )
    args_schema: type[BaseModel] = TransferInput

    def _run(self, task: str, context: str = "") -> str:
        from agents.shared.slack_tools import transfer_to_support_sync

        return transfer_to_support_sync(task, context)


class TransferToPMTool(BaseTool if CREWAI_AVAILABLE else object):
    """Transfer a task to ProductManager."""

    name: str = "transfer_to_pm"
    description: str = (
        "Transfer a product task to ProductManager. "
        "Use for prioritization, requirements, or feature decisions."
    )
    args_schema: type[BaseModel] = TransferInput

    def _run(self, task: str, context: str = "") -> str:
        from agents.shared.slack_tools import transfer_to_pm_sync

        return transfer_to_pm_sync(task, context)


class TransferToMarketerTool(BaseTool if CREWAI_AVAILABLE else object):
    """Transfer a task to MarketingManager."""

    name: str = "transfer_to_marketer"
    description: str = (
        "Transfer a marketing task to MarketingManager. "
        "Use for release announcements, social media, or marketing communication."
    )
    args_schema: type[BaseModel] = TransferInput

    def _run(self, task: str, context: str = "") -> str:
        from agents.shared.slack_tools import transfer_to_marketer_sync

        return transfer_to_marketer_sync(task, context)


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


def get_swe_transfer_tools() -> list:
    """Get transfer tools for SoftwareEngineer (can't transfer to self)."""
    return [
        TransferToSRETool(),
        TransferToReleaseTool(),
        TransferToSupportTool(),
        TransferToPMTool(),
    ]


def get_sre_transfer_tools() -> list:
    """Get transfer tools for SiteReliabilityEngineer (can't transfer to self)."""
    return [
        TransferToSWETool(),
        TransferToReleaseTool(),
        TransferToSupportTool(),
        TransferToPMTool(),
    ]


def get_release_transfer_tools() -> list:
    """Get transfer tools for ReleaseEngineer (can't transfer to self)."""
    return [
        TransferToSWETool(),
        TransferToSRETool(),
        TransferToSupportTool(),
        TransferToPMTool(),
        TransferToMarketerTool(),
    ]


def get_support_transfer_tools() -> list:
    """Get transfer tools for SupportEngineer (can't transfer to self)."""
    return [
        TransferToSWETool(),
        TransferToSRETool(),
        TransferToPMTool(),
    ]


def get_pm_transfer_tools() -> list:
    """Get transfer tools for ProductManager (can delegate to all)."""
    return [
        TransferToSWETool(),
        TransferToSRETool(),
        TransferToReleaseTool(),
        TransferToSupportTool(),
        TransferToMarketerTool(),
    ]


def get_marketer_transfer_tools() -> list:
    """Get transfer tools for MarketingManager (limited transfers)."""
    return [
        TransferToReleaseTool(),
        TransferToPMTool(),
    ]
