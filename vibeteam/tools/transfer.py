"""
Transfer Tools - Swarm-pattern handoff tools for agent delegation.

These tools enable agents to transfer control to other agents in the swarm.
Based on the AutoGen Swarm pattern where handoffs are tool-based rather than
LLM-selected speaker.

Supports two modes:
1. In-memory handoffs (default): Returns HANDOFF: signal for SwarmOrchestrator
2. Slack handoffs: Posts @mention to Slack channel for async agent pickup
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Special prefix that signals a handoff
HANDOFF_PREFIX = "HANDOFF:"

# Global Slack context for handoffs - set by run_slack_agent.py
_slack_context: dict[str, Any] = {}


def set_slack_handoff_context(
    slack_connector: Any,
    channel: str,
    thread_ts: str | None = None,
    from_agent: str = "",
) -> None:
    """
    Set the Slack context for handoffs.

    When set, transfer tools will post @mentions to Slack instead of
    returning in-memory handoff signals.

    Args:
        slack_connector: SlackConnector instance
        channel: Channel to post handoffs to
        thread_ts: Thread to reply in (for context continuity)
        from_agent: Name of the agent initiating handoffs
    """
    global _slack_context
    _slack_context = {
        "connector": slack_connector,
        "channel": channel,
        "thread_ts": thread_ts,
        "from_agent": from_agent,
    }
    logger.debug(f"Slack handoff context set: channel={channel}, thread={thread_ts}")


def clear_slack_handoff_context() -> None:
    """Clear the Slack context, reverting to in-memory handoffs."""
    global _slack_context
    _slack_context = {}


def is_slack_handoff_enabled() -> bool:
    """Check if Slack handoff mode is enabled."""
    return bool(_slack_context.get("connector"))


@dataclass
class HandoffResult(ToolResult):
    """Result from a handoff tool execution."""

    target_agent: str = ""
    task: str = ""
    posted_to_slack: bool = False
    slack_message_ts: str = ""


# Agent key to display name mapping
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "supervisor": "ProductManager",
    "pm": "ProductManager",
    "swe": "SoftwareEngineer",
    "sre": "SiteReliabilityEngineer",
    "release": "ReleaseEngineer",
    "support": "SupportEngineer",
    "marketer": "MarketingManager",
}


def create_handoff_result(target: str, task: str, context: str = "") -> HandoffResult:
    """
    Create a handoff result.

    If Slack context is set, posts @mention to Slack.
    Otherwise, returns in-memory handoff signal.
    """
    global _slack_context

    # Check if we should post to Slack
    if is_slack_handoff_enabled():
        try:
            connector = _slack_context["connector"]
            channel = _slack_context["channel"]
            thread_ts = _slack_context.get("thread_ts")
            from_agent = _slack_context.get("from_agent", "Agent")

            # Format the handoff message
            target_name = AGENT_DISPLAY_NAMES.get(target, target.upper())
            handoff_message = f"I need help from {target_name}.\n\n**Task:** {task}"
            if context:
                handoff_message += f"\n**Context:** {context}"

            # Post to Slack with @mention
            msg = connector.mention_agent(
                channel=channel,
                agent_key=target,
                message=handoff_message,
                thread_ts=thread_ts,
            )

            logger.info(f"Posted Slack handoff to @{target}: {task[:50]}...")

            return HandoffResult(
                success=True,
                output=f"Handed off to {target_name} via Slack. They will pick up the task.",
                target_agent=target,
                task=task,
                posted_to_slack=True,
                slack_message_ts=msg.ts,
                metadata={"context": context, "type": "slack_handoff", "channel": channel},
            )
        except Exception as e:
            logger.error(f"Failed to post Slack handoff: {e}")
            # Fall through to in-memory handoff

    # In-memory handoff (default)
    return HandoffResult(
        success=True,
        output=f"{HANDOFF_PREFIX}{target}:{task}",
        target_agent=target,
        task=task,
        metadata={"context": context, "type": "handoff"},
    )


def is_handoff_result(output: str) -> bool:
    """Check if a result is a handoff signal."""
    return output.startswith(HANDOFF_PREFIX)


def parse_handoff(output: str) -> tuple[str, str] | None:
    """Parse a handoff signal into (target_agent, task)."""
    if not is_handoff_result(output):
        return None
    # Format: HANDOFF:agent_key:task
    parts = output[len(HANDOFF_PREFIX) :].split(":", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""


class TransferToSupervisorTool(BaseTool):
    """Transfer control back to the ProductManager for synthesis or re-routing."""

    name = "transfer_to_supervisor"
    description = (
        "Transfer back to the ProductManager when your task is complete, "
        "or when you need the supervisor to synthesize results, make decisions, or route to another agent."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Summary of what you accomplished or the result to report",
                        },
                        "needs_followup": {
                            "type": "boolean",
                            "description": "Whether further action is needed from another agent",
                            "default": False,
                        },
                    },
                    "required": ["result"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, result: str, needs_followup: bool = False, **kwargs: Any
    ) -> HandoffResult:
        context = "needs_followup" if needs_followup else "complete"
        return create_handoff_result("supervisor", result, context)


class TransferToSWETool(BaseTool):
    """Transfer task to SoftwareEngineer for implementation."""

    name = "transfer_to_swe"
    description = (
        "Transfer to SoftwareEngineer for code implementation, bug fixes, "
        "code review, pull requests, or any coding-related tasks."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The coding task or request for the Software Engineer",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context from the conversation",
                            "default": "",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                            "description": "Priority level of the task",
                            "default": "medium",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, task: str, context: str = "", priority: str = "medium", **kwargs: Any
    ) -> HandoffResult:
        return create_handoff_result("swe", task, f"priority={priority}, context={context}")


class TransferToSRETool(BaseTool):
    """Transfer task to SiteReliabilityEngineer for infrastructure/monitoring."""

    name = "transfer_to_sre"
    description = (
        "Transfer to SiteReliabilityEngineer for monitoring, Sentry errors, "
        "incidents, production health, observability, and infrastructure issues."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The monitoring or infrastructure task for the Reliability Engineer",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context about the issue or request",
                            "default": "",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, task: str, context: str = "", **kwargs: Any
    ) -> HandoffResult:
        return create_handoff_result("sre", task, context)


class TransferToReleaseTool(BaseTool):
    """Transfer task to ReleaseEngineer for deployments and versioning."""

    name = "transfer_to_release"
    description = (
        "Transfer to ReleaseEngineer for deployments, releases, "
        "versioning, changelogs, and publishing."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The release or deployment task",
                        },
                        "version": {
                            "type": "string",
                            "description": "Version number if applicable",
                            "default": "",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, task: str, version: str = "", **kwargs: Any
    ) -> HandoffResult:
        return create_handoff_result("release", task, f"version={version}" if version else "")


class TransferToSupportTool(BaseTool):
    """Transfer task to SupportEngineer for customer issues."""

    name = "transfer_to_support"
    description = (
        "Transfer to SupportEngineer for customer issues, support tickets, "
        "documentation, FAQs, and user assistance."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The support task or customer issue",
                        },
                        "customer_info": {
                            "type": "string",
                            "description": "Customer information if available",
                            "default": "",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, task: str, customer_info: str = "", **kwargs: Any
    ) -> HandoffResult:
        return create_handoff_result(
            "support", task, f"customer={customer_info}" if customer_info else ""
        )


class TransferToMarketerTool(BaseTool):
    """Transfer task to MarketingManager for content and announcements."""

    name = "transfer_to_marketer"
    description = (
        "Transfer to MarketingManager for social media posts, announcements, "
        "content creation, and marketing activities."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The marketing or content task",
                        },
                        "platform": {
                            "type": "string",
                            "enum": ["twitter", "linkedin", "reddit", "all"],
                            "description": "Target platform(s)",
                            "default": "all",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, task: str, platform: str = "all", **kwargs: Any
    ) -> HandoffResult:
        return create_handoff_result("marketer", task, f"platform={platform}")


class TransferToPMTool(BaseTool):
    """Transfer task to ProductManager for requirements and prioritization."""

    name = "transfer_to_pm"
    description = (
        "Transfer to ProductManager for requirements gathering, prioritization, "
        "user stories, roadmap decisions, and product strategy."
    )

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The product management task or question",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context",
                            "default": "",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    async def execute(  # type: ignore[override]
        self, task: str, context: str = "", **kwargs: Any
    ) -> HandoffResult:
        return create_handoff_result("pm", task, context)


# Agent key to tool mapping
TRANSFER_TOOLS: dict[str, type[BaseTool]] = {
    "supervisor": TransferToSupervisorTool,
    "swe": TransferToSWETool,
    "sre": TransferToSRETool,
    "release": TransferToReleaseTool,
    "support": TransferToSupportTool,
    "marketer": TransferToMarketerTool,
    "pm": TransferToPMTool,
}


def get_transfer_tools_for_agent(agent_key: str) -> list[BaseTool]:
    """
    Get transfer tools for an agent, excluding their own transfer tool.

    For Slack-based inter-agent communication, all agents can transfer to
    any other agent (not just supervisor). This enables direct handoffs
    like Support -> SWE for bug fixes.

    Args:
        agent_key: The agent's key (e.g., "swe", "sre", "supervisor")

    Returns:
        List of transfer tools the agent can use
    """
    tools = []
    for key, tool_class in TRANSFER_TOOLS.items():
        # Skip self-transfer
        if key == agent_key:
            continue
        # PM and supervisor are the same role
        if key == "pm" and agent_key == "supervisor":
            continue
        if key == "supervisor" and agent_key == "pm":
            continue
        tools.append(tool_class())
    return tools


def get_all_transfer_tools() -> list[BaseTool]:
    """Get all transfer tools."""
    return [tool_class() for tool_class in TRANSFER_TOOLS.values()]
