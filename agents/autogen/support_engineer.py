"""
SupportEngineer agent using AutoGen.

Capabilities:
- Email management (Gmail)
- Calendar scheduling (Google Calendar)
- Error tracking (Sentry)
- LLM observability (Langfuse)
- Customer support ticket handling
"""

import asyncio
import os
from datetime import datetime
from typing import Any

from agents.config import SUPPORT_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store
from agents.shared.handoff import HANDOFF_PROMPT

# AutoGen imports - will fail gracefully if not installed
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_core.models import ModelFamily
    from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False
    AssistantAgent = None
    TaskResult = None
    AzureOpenAIChatCompletionClient = None
    ModelFamily = None

# Model info for custom Azure deployments
AZURE_MODEL_INFO = {
    "vision": True,
    "function_calling": True,
    "json_output": True,
    "family": "gpt-4o",
    "structured_output": True,
}


SUPPORT_ENGINEER_SYSTEM_PROMPT = f"""You are Grace, the Support Engineer for VibeTeam.

## CRITICAL: How to Respond

You MUST use `send_message()` to post your response to Slack. Never just return text.
Your message will be automatically prefixed with [SupportEngineer:session_id].

Example:
```
send_message("I checked Sentry and found 3 errors. @ReleaseEngineer please investigate.")
```

## Available Tools

- `send_message(message)` - Post your response to Slack (REQUIRED for all responses)
- `get_sentry_issues(project, hours, limit)` - Get Sentry issues for error monitoring
- `get_langfuse_traces(hours, limit, name)` - Get Langfuse traces for LLM observability
- `list_emails(max_results, query)` - List emails from Gmail
- `send_email(to, subject, body)` - Send an email
- `list_calendar_events(max_results)` - List calendar events
- `create_calendar_event(summary, start_time, end_time, attendees)` - Create calendar event
- `search_docs(query)` - Search product documentation
- `create_support_ticket(customer_email, subject, description, priority)` - Create support ticket
- `read_slack_channel()` - Read recent Slack messages

## Tool Usage Requirements

IMPORTANT:
- For Sentry/error tasks: ALWAYS call `get_sentry_issues` first to get real data
- For LLM monitoring: ALWAYS call `get_langfuse_traces` to get real traces
- NEVER generate fake data or respond from memory - use tools to get real information
- After gathering data, use `send_message()` to post your findings

## Your Responsibilities

1. **Customer Support**: Handle customer inquiries and support tickets
2. **Email Management**: Read and respond to support emails
3. **Calendar Management**: Schedule meetings and manage team calendar
4. **Error Tracking**: Monitor Sentry for errors and escalate critical issues
5. **LLM Observability**: Review Langfuse traces for quality issues

## Email Guidelines
- Respond promptly and professionally
- Escalate urgent issues to the appropriate team member
- Use templates for common responses
- Always verify customer context before responding

## Error Monitoring
- Critical errors: Escalate immediately to @ReleaseEngineer
- High-frequency errors: Create GitHub issue
- Performance issues: Log for weekly review

{HANDOFF_PROMPT}
"""


# Import shared tool functions - these use real connectors
from agents.shared.calendar_tools import (
    create_calendar_event,
    list_calendar_events,
)
from agents.shared.docs_tools import (
    get_doc_content,
    list_docs,
    search_docs,
)
from agents.shared.gmail_tools import (
    list_emails,
    send_email,
)
from agents.shared.langfuse_tools import (
    get_langfuse_traces,
)
from agents.shared.slack_tools import (
    read_slack_channel,
    read_slack_thread,
    send_message,
)


async def get_sentry_issues(project: str | None = None, hours: int = 24, limit: int = 10) -> str:
    """Get unresolved issues from Sentry.

    Args:
        project: Sentry project slug (None for all projects)
        hours: Time window in hours (default: 24)
        limit: Maximum issues to return (default: 10)

    Returns:
        List of Sentry issues with details
    """
    import os

    try:
        from vibeteam.connectors.sentry import SentryConnector

        auth_token = os.getenv("SENTRY_AUTH_TOKEN")
        if not auth_token:
            return "Error: SENTRY_AUTH_TOKEN not configured. Please set this environment variable."

        connector = SentryConnector(auth_token=auth_token)
        issues = connector.fetch_unresolved_issues(project=project, hours=hours, limit=limit)

        if not issues:
            return f"No unresolved issues found in the last {hours} hours."

        result = (
            f"=== Sentry Issues (last {hours}h) ===\nFound {len(issues)} unresolved issues:\n\n"
        )
        for issue in issues:
            result += f"**[{issue.project}] {issue.short_id}**: {issue.title}\n"
            result += f"  - Level: {issue.level} | Count: {issue.count} | Users affected: {issue.user_count}\n"
            result += (
                f"  - First seen: {issue.first_seen[:10]} | Last seen: {issue.last_seen[:10]}\n"
            )
            result += f"  - URL: {issue.permalink}\n\n"

        return result

    except ImportError:
        return "Error: vibeteam.connectors.sentry module not available. Please install the vibeteam package."
    except Exception as e:
        return f"Error fetching Sentry issues: {e}"


# get_langfuse_traces is imported from agents.shared.langfuse_tools


async def create_support_ticket(
    customer_email: str,
    subject: str,
    description: str,
    priority: str = "medium",
) -> str:
    """Create a support ticket.

    Args:
        customer_email: Customer's email address
        subject: Ticket subject
        description: Detailed description of the issue
        priority: Priority level (low, medium, high, critical)

    Returns:
        Ticket creation status
    """
    ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    return f"""
=== Support Ticket Created ===
Ticket ID: {ticket_id}
Customer: {customer_email}
Subject: {subject}
Priority: {priority.upper()}
Description:
{description}

Status: Created (simulated)
Note: In production, this would integrate with your ticketing system
"""


class AutoGenSupportEngineer:
    """Support Engineer agent using AutoGen."""

    def __init__(self, config: AgentConfig | None = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError(
                "AutoGen not installed. Run: pip install 'autogen-agentchat' 'autogen-ext[openai,azure]'"
            )

        self.config = config or SUPPORT_ENGINEER_CONFIG
        self.model_client = self._create_model_client()
        self.agent = self._create_agent()

    def _create_model_client(self) -> "AzureOpenAIChatCompletionClient":
        """Create Azure OpenAI model client."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if model_name.startswith("azure/"):
            model_name = model_name[6:]

        return AzureOpenAIChatCompletionClient(
            azure_deployment=model_name,
            model=model_name,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=self.config.llm.api_base or "",
            api_key=self.config.llm.api_key or "",
            model_info=AZURE_MODEL_INFO,
        )

    def _create_agent(self) -> "AssistantAgent":
        """Create AutoGen AssistantAgent with tools."""
        return AssistantAgent(
            name="SupportEngineer",
            model_client=self.model_client,
            tools=[
                # Core support tools
                list_emails,
                send_email,
                list_calendar_events,
                create_calendar_event,
                get_sentry_issues,
                get_langfuse_traces,
                create_support_ticket,
                search_docs,
                list_docs,
                get_doc_content,
                # Slack communication tools (send_message is PRIMARY for responses)
                send_message,
                read_slack_channel,
                read_slack_thread,
            ],
            system_message=SUPPORT_ENGINEER_SYSTEM_PROMPT,
            description="Support Engineer for customer support, email, calendar, and monitoring.",
            reflect_on_tool_use=True,  # Summarize after tool calls
            max_tool_iterations=5,  # Allow multiple tool iterations
        )

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Support Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, email, ephemeral)
            context_id: ID for the context

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="autogen",
            role="support_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        # Run the agent
        result: TaskResult = await self.agent.run(task=task)

        # Extract response from result
        # Priority: 1) send_message tool call content, 2) non-empty TextMessage
        response = ""
        if result.messages:
            import json

            from autogen_agentchat.messages import TextMessage, ToolCallRequestEvent

            # First, look for send_message tool calls - this is the actual response
            for msg in reversed(result.messages):
                if isinstance(msg, ToolCallRequestEvent) and msg.source == "SupportEngineer":
                    for call in msg.content:
                        if hasattr(call, "name") and call.name == "send_message":
                            try:
                                args = json.loads(call.arguments)
                                if args.get("message"):
                                    response = args["message"]
                                    break
                            except (json.JSONDecodeError, AttributeError):
                                pass
                    if response:
                        break

            # Fallback: get the last non-empty TextMessage from the assistant
            if not response:
                for msg in reversed(result.messages):
                    if isinstance(msg, TextMessage) and msg.source == "SupportEngineer":
                        if msg.content and str(msg.content).strip():
                            response = str(msg.content)
                            break

        # Update session
        session.add_message("user", task)
        session.add_message("assistant", response)
        get_session_store().save(session)

        return {
            "response": response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "autogen",
            "agent": "support_engineer",
        }

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Sync version of run_async."""
        return asyncio.run(self.run_async(task, context_type, context_id, **kwargs))

    async def close(self) -> None:
        """Close the model client connection."""
        if self.model_client:
            await self.model_client.close()


def create_support_engineer(
    config: AgentConfig | None = None,
) -> AutoGenSupportEngineer:
    """Factory function to create Support Engineer agent."""
    return AutoGenSupportEngineer(config)
