"""
SupportEngineer agent using OpenHands.

Capabilities:
- Gmail access via MCP for email management
- Google Calendar via MCP for scheduling
- Langfuse integration for LLM observability
- Sentry integration for error tracking
"""

import os
from typing import Any

from agents.config import (
    AgentConfig,
    SUPPORT_ENGINEER_CONFIG,
    get_mcp_config_dict,
)
from agents.sessions import get_or_create_session, get_session_store

try:
    from openhands.sdk import Agent, Conversation, LLM, Tool

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    Agent = None
    Conversation = None


SUPPORT_ENGINEER_SYSTEM_PROMPT = """You are Grace, the Support Engineer for VibeTeam.

Your responsibilities:
1. **Email Support**: Read, triage, and respond to customer emails
2. **Scheduling**: Manage calendar events and meeting requests
3. **Error Analysis**: Investigate Sentry errors and provide solutions
4. **Observability**: Monitor Langfuse for LLM performance issues

## Tools Available
- Gmail MCP: Read emails, send replies, search inbox
- Google Calendar MCP: Create events, check availability
- Sentry MCP: Query errors, get stack traces
- Langfuse: Query traces, analyze LLM calls

## Email Response Guidelines
1. Acknowledge the issue
2. Provide timeline for resolution
3. Include relevant documentation links
4. Sign off as "Grace, VibeTeam Support"

## Escalation Path
- Technical bugs -> @SoftwareEngineer
- Release issues -> @ReleaseEngineer
- Public communications -> @MarketingManager

## Common Queries
- Password reset: Link to /reset-password
- API keys: Link to /settings/api
- Billing: Escalate to billing@vibetech.co

When responding to emails:
1. Always check for similar past issues
2. Be empathetic and professional
3. Follow up within 24 hours
"""


class OpenHandsSupportEngineer:
    """Support Engineer agent using OpenHands SDK."""

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or SUPPORT_ENGINEER_CONFIG
        self.llm = self._create_llm()
        self.agent = self._create_agent()

    def _create_llm(self) -> "LLM":
        """Create OpenHands LLM instance."""
        return LLM(
            model=self.config.llm.model,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            temperature=self.config.llm.temperature,
        )

    def _create_agent(self) -> "Agent":
        """Create OpenHands Agent with support MCP tools."""
        mcp_config = get_mcp_config_dict(self.config.mcp_servers)

        return Agent(
            llm=self.llm,
            tools=[],  # Primarily uses MCP tools
            mcp_config=mcp_config if mcp_config["mcpServers"] else None,
            system_prompt=SUPPORT_ENGINEER_SYSTEM_PROMPT,
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """
        Run a task with the Support Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (email, ticket, slack, ephemeral)
            context_id: ID for the context (email message ID, ticket number)
            workspace: Working directory for the agent

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="support_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        workspace = workspace or os.getcwd()
        conversation = Conversation(
            agent=self.agent,
            workspace=workspace,
            persistence_dir=self.config.session.storage_path,
            conversation_id=session.session_id,
        )

        conversation.send_message(task)
        conversation.run()

        response = conversation.get_last_assistant_message()

        session.add_message("user", task)
        session.add_message("assistant", response)
        get_session_store().save(session)

        return {
            "response": response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "openhands",
            "agent": "support_engineer",
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, workspace)


def create_support_engineer(config: AgentConfig | None = None) -> OpenHandsSupportEngineer:
    """Factory function to create Support Engineer agent."""
    return OpenHandsSupportEngineer(config)
