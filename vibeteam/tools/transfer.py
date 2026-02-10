"""
Transfer Tools - Swarm-pattern handoff tools for agent delegation.

These tools enable agents to transfer control to other agents in the swarm.
Based on the AutoGen Swarm pattern where handoffs are tool-based rather than
LLM-selected speaker.
"""

from dataclasses import dataclass
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult

# Special prefix that signals a handoff
HANDOFF_PREFIX = "HANDOFF:"


@dataclass
class HandoffResult(ToolResult):
    """Result from a handoff tool execution."""

    target_agent: str = ""
    task: str = ""


def create_handoff_result(target: str, task: str, context: str = "") -> HandoffResult:
    """Create a handoff result."""
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
    """Transfer control back to the Supervisor/PM for synthesis or re-routing."""

    name = "transfer_to_supervisor"
    description = (
        "Transfer back to the Supervisor (Product Manager) when your task is complete, "
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
    """Transfer task to Software Engineer for implementation."""

    name = "transfer_to_swe"
    description = (
        "Transfer to Software Engineer (Ada) for code implementation, bug fixes, "
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
    """Transfer task to Reliability Engineer for infrastructure/monitoring."""

    name = "transfer_to_sre"
    description = (
        "Transfer to Reliability Engineer (Heisenberg) for monitoring, Sentry errors, "
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
    """Transfer task to Release Engineer for deployments and versioning."""

    name = "transfer_to_release"
    description = (
        "Transfer to Release Engineer (Jenkins) for deployments, releases, "
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
    """Transfer task to Support Engineer for customer issues."""

    name = "transfer_to_support"
    description = (
        "Transfer to Support Engineer (Watson) for customer issues, support tickets, "
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
    """Transfer task to Marketer for content and announcements."""

    name = "transfer_to_marketer"
    description = (
        "Transfer to Marketer (Bernays) for social media posts, announcements, "
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
    """Transfer task to Product Manager for requirements and prioritization."""

    name = "transfer_to_pm"
    description = (
        "Transfer to Product Manager (Curie) for requirements gathering, prioritization, "
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

    Args:
        agent_key: The agent's key (e.g., "swe", "sre", "supervisor")

    Returns:
        List of transfer tools the agent can use
    """
    tools = []
    for key, tool_class in TRANSFER_TOOLS.items():
        # Always include transfer to supervisor for non-supervisor agents
        if key == "supervisor" and agent_key != "supervisor":
            tools.append(tool_class())
        # Include other agent transfers for supervisor
        elif key != agent_key and key != "supervisor" and agent_key == "supervisor":
            tools.append(tool_class())
        # PM is also the supervisor, so treat them as same
        elif key == "pm" and agent_key == "supervisor":
            continue  # Don't add pm transfer for supervisor
    return tools


def get_all_transfer_tools() -> list[BaseTool]:
    """Get all transfer tools."""
    return [tool_class() for tool_class in TRANSFER_TOOLS.values()]
