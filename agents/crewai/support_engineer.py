"""
SupportEngineer agent using CrewAI.

Capabilities:
- Email management (Gmail integration)
- Calendar scheduling (Google Calendar)
- Error tracking (Sentry)
- LLM observability (Langfuse)
"""

import os
from typing import Any

from agents.config import SUPPORT_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store

try:
    from crewai import Agent, Crew, Process, Task
    from crewai.llm import LLM
    from crewai.tools import BaseTool

    CREWAI_AVAILABLE = True
except ImportError:
    CREWAI_AVAILABLE = False
    Agent = None
    Task = None
    Crew = None
    LLM = None


SUPPORT_ENGINEER_BACKSTORY = """You are Grace, the Support Engineer for VibeTeam.
You have deep expertise in:
- Customer support and communication
- Email and calendar management
- Error analysis and debugging
- LLM observability and monitoring

You are empathetic, thorough, and solutions-oriented.
You ensure every customer feels heard and helped.
"""

SUPPORT_ENGINEER_GOAL = """Provide excellent customer support, manage communications,
and monitor system health for VibeTeam."""


class EmailSearchTool(BaseTool if CREWAI_AVAILABLE else object):
    """Search emails in Gmail."""

    name: str = "search_emails"
    description: str = "Search emails in Gmail. Input: search query."

    def _run(self, query: str) -> str:
        """Search emails (mock implementation)."""
        # In production, use Gmail API
        return f"Email search results for: {query}\n[Mock results - integrate with Gmail API]"


class SendEmailTool(BaseTool if CREWAI_AVAILABLE else object):
    """Send an email via Gmail."""

    name: str = "send_email"
    description: str = "Send an email. Input: JSON with 'to', 'subject', and 'body' keys."

    def _run(self, input_data: str) -> str:
        """Send email (mock implementation)."""
        import json

        try:
            data = json.loads(input_data)
            to = data.get("to")
            subject = data.get("subject")
            body = data.get("body")

            if not all([to, subject, body]):
                return "Error: 'to', 'subject', and 'body' are required"

            # In production, use Gmail API
            return f"Email sent to {to} with subject: {subject}\n[Mock - integrate with Gmail API]"
        except Exception as e:
            return f"Error sending email: {e}"


class CalendarTool(BaseTool if CREWAI_AVAILABLE else object):
    """Manage Google Calendar events."""

    name: str = "calendar"
    description: str = "Manage calendar. Input: JSON with 'action' (list/create) and event details."

    def _run(self, input_data: str) -> str:
        """Manage calendar (mock implementation)."""
        import json

        try:
            data = json.loads(input_data)
            action = data.get("action", "list")

            if action == "list":
                return "Upcoming events:\n[Mock - integrate with Google Calendar API]"
            elif action == "create":
                title = data.get("title", "Meeting")
                return f"Created event: {title}\n[Mock - integrate with Google Calendar API]"
            else:
                return f"Unknown action: {action}"
        except Exception as e:
            return f"Error with calendar: {e}"


class SentryTool(BaseTool if CREWAI_AVAILABLE else object):
    """Query Sentry for errors using real API."""

    name: str = "sentry"
    description: str = (
        "Query Sentry for unresolved errors. Input: optional JSON with 'project', 'hours', 'limit' keys."
    )

    def _run(self, query: str = "") -> str:
        """Query Sentry for unresolved issues."""
        import json
        import os

        try:
            from vibeteam.connectors.sentry import SentryConnector

            auth_token = os.getenv("SENTRY_AUTH_TOKEN")
            if not auth_token:
                return "Error: SENTRY_AUTH_TOKEN not configured."

            # Parse optional parameters from query
            project = None
            hours = 24
            limit = 10

            if query:
                try:
                    params = json.loads(query)
                    project = params.get("project")
                    hours = params.get("hours", 24)
                    limit = params.get("limit", 10)
                except json.JSONDecodeError:
                    # Query is just a search string, use defaults
                    pass

            connector = SentryConnector(auth_token=auth_token)
            issues = connector.fetch_unresolved_issues(project=project, hours=hours, limit=limit)

            if not issues:
                return f"No unresolved issues found in the last {hours} hours."

            result = f"Found {len(issues)} unresolved issues:\n\n"
            for issue in issues:
                result += f"**[{issue.project}] {issue.short_id}**: {issue.title}\n"
                result += (
                    f"  Level: {issue.level} | Count: {issue.count} | Users: {issue.user_count}\n"
                )
                result += f"  URL: {issue.permalink}\n\n"

            return result

        except ImportError:
            return "Error: vibeteam.connectors.sentry module not available."
        except Exception as e:
            return f"Error fetching Sentry issues: {e}"


class CrewAISupportEngineer:
    """Support Engineer agent using CrewAI."""

    def __init__(self, config: AgentConfig | None = None):
        if not CREWAI_AVAILABLE:
            raise ImportError("CrewAI not installed. Run: pip install crewai")

        self.config = config or SUPPORT_ENGINEER_CONFIG
        self.tools = self._create_tools()
        self.agent = self._create_agent()

    def _create_tools(self) -> list:
        """Create tools for the agent."""
        return [
            EmailSearchTool(),
            SendEmailTool(),
            CalendarTool(),
            SentryTool(),
        ]

    def _create_agent(self) -> "Agent":
        """Create CrewAI Agent."""
        # CrewAI uses litellm which needs azure/<deployment> format
        model_name = self.config.llm.model or "gpt-4.1-mini"
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        # Create LLM with explicit Azure configuration
        llm = LLM(
            model=model_name,
            provider="litellm",
            api_base=self.config.llm.api_base,
            api_key=self.config.llm.api_key,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
        )

        return Agent(
            role="Support Engineer",
            goal=SUPPORT_ENGINEER_GOAL,
            backstory=SUPPORT_ENGINEER_BACKSTORY,
            tools=self.tools,
            verbose=self.config.verbose,
            llm=llm,
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a task with the Support Engineer agent."""
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="crewai",
            role="support_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        crew_task = Task(
            description=task,
            agent=self.agent,
            expected_output="Summary of support actions taken or analysis completed.",
        )

        crew = Crew(
            agents=[self.agent],
            tasks=[crew_task],
            process=Process.sequential,
            verbose=self.config.verbose,
        )

        result = crew.kickoff()

        session.add_message("user", task)
        session.add_message("assistant", str(result))
        get_session_store().save(session)

        return {
            "response": str(result),
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "crewai",
            "agent": "support_engineer",
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(self.run, task, context_type, context_id, **kwargs)


def create_support_engineer(config: AgentConfig | None = None) -> CrewAISupportEngineer:
    """Factory function to create Support Engineer agent."""
    return CrewAISupportEngineer(config)
