"""
SupportEngineer agent using OpenHands.

Capabilities:
- Gmail access via MCP for email management
- Google Calendar via MCP for scheduling
- Langfuse integration for LLM observability
- Sentry integration for error tracking

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import tempfile
from typing import Any

from agents.config import SUPPORT_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store


def fetch_sentry_context(hours: int = 24, limit: int = 10) -> str:
    """Fetch Sentry issues and format as context for the agent."""
    try:
        from vibeteam.connectors.sentry import SentryConnector

        auth_token = os.getenv("SENTRY_AUTH_TOKEN")
        if not auth_token:
            return "Sentry: SENTRY_AUTH_TOKEN not configured."

        connector = SentryConnector(auth_token=auth_token)
        issues = connector.fetch_unresolved_issues(hours=hours, limit=limit)

        if not issues:
            return f"Sentry: No unresolved issues found in the last {hours} hours."

        result = f"## Current Sentry Issues (last {hours}h)\n\n"
        for issue in issues:
            result += f"### [{issue.project}] {issue.short_id}\n"
            result += f"**{issue.title}**\n"
            result += f"- Level: {issue.level} | Count: {issue.count} | Users: {issue.user_count}\n"
            result += f"- First seen: {issue.first_seen[:10]} | Last seen: {issue.last_seen[:10]}\n"
            result += f"- URL: {issue.permalink}\n\n"

        return result

    except ImportError:
        return "Sentry: vibeteam.connectors.sentry module not available."
    except Exception as e:
        return f"Sentry: Error fetching issues - {e}"


try:
    from openhands.sdk import LLM, Agent, LocalConversation

    OPENHANDS_AVAILABLE = True
except ImportError:
    OPENHANDS_AVAILABLE = False
    LLM = None
    Agent = None
    LocalConversation = None


SUPPORT_ENGINEER_CONTEXT = """You are Grace, the Support Engineer for VibeTeam.

Your responsibilities:
1. **Email Support**: Read, triage, and respond to customer emails
2. **Scheduling**: Manage calendar events and meeting requests
3. **Issue Tracking**: Monitor Sentry for errors and create GitHub issues
4. **LLM Observability**: Review Langfuse traces for quality issues

## Tools Available
- Gmail MCP: Read and send emails
- Google Calendar MCP: View and manage calendar
- Sentry API: Query errors and issues
- Langfuse API: Review LLM traces

## Communication
- Post updates to Slack #ai-team
- Tag @ProductManager for feature requests
- Tag @SoftwareEngineer for bug fixes

When you complete a task, summarize what was done and any next steps.
"""


class OpenHandsSupportEngineer:
    """
    Support Engineer agent using OpenHands SDK.

    Uses OpenHands' agentic loop for customer support tasks.
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or SUPPORT_ENGINEER_CONFIG

    def _create_llm(self) -> "LLM":
        """Create LLM with Azure configuration."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return LLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,
        )

    def _create_agent(self, llm: "LLM") -> "Agent":
        """Create Agent with LLM."""
        return Agent(
            llm=llm,
            system_prompt_kwargs={
                "agent_context": SUPPORT_ENGINEER_CONTEXT,
            },
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Support Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context
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

        llm = self._create_llm()
        agent = self._create_agent(llm)

        # Use provided workspace or create temporary one
        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        try:
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
            )

            # Check if task involves Sentry and inject real data
            task_lower = task.lower()
            sentry_context = ""
            if "sentry" in task_lower or "error" in task_lower or "issue" in task_lower:
                sentry_context = f"\n\n{fetch_sentry_context()}\n"

            full_task = f"{SUPPORT_ENGINEER_CONTEXT}{sentry_context}\n\nTask: {task}"
            response = conversation.ask_agent(full_task)

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

        finally:
            if temp_dir:
                try:
                    conversation.close()
                except Exception:
                    pass
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run, task, context_type, context_id, workspace, **kwargs
        )


def create_support_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsSupportEngineer:
    """Factory function to create Support Engineer agent."""
    return OpenHandsSupportEngineer(config)
