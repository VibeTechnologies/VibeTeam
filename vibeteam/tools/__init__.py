"""
VibeTeam Tools - OpenHands Tool wrappers for external service connectors.

Tools are the interface between agents and external services.
Each tool wraps an existing connector and exposes it as an OpenHands-compatible tool.
"""

from vibeteam.tools.github import GitHubTool
from vibeteam.tools.gmail import GmailTool
from vibeteam.tools.health import HealthCheckTool
from vibeteam.tools.langfuse import LangfuseTool
from vibeteam.tools.sentry import SentryTool
from vibeteam.tools.slack import SlackTool
from vibeteam.tools.transfer import (
    TRANSFER_TOOLS,
    HandoffResult,
    TransferToMarketerTool,
    TransferToPMTool,
    TransferToReleaseTool,
    TransferToSRETool,
    TransferToSupervisorTool,
    TransferToSupportTool,
    TransferToSWETool,
    get_all_transfer_tools,
    get_transfer_tools_for_agent,
    is_handoff_result,
    parse_handoff,
)

__all__ = [
    "GitHubTool",
    "GmailTool",
    "HealthCheckTool",
    "LangfuseTool",
    "SentryTool",
    "SlackTool",
    # Transfer tools for Swarm pattern
    "TRANSFER_TOOLS",
    "HandoffResult",
    "TransferToMarketerTool",
    "TransferToPMTool",
    "TransferToReleaseTool",
    "TransferToSRETool",
    "TransferToSupervisorTool",
    "TransferToSupportTool",
    "TransferToSWETool",
    "get_all_transfer_tools",
    "get_transfer_tools_for_agent",
    "is_handoff_result",
    "parse_handoff",
]
