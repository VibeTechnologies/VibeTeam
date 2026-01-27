"""
AutoGen team orchestration for VibeTeam.

Uses SelectorGroupChat for dynamic agent selection based on task content.
"""

import asyncio
import os
from typing import Any

from agents.config import AgentConfig
from agents.sessions import get_or_create_session, get_session_store

# Import agent modules (will create agents on demand)
from agents.autogen.release_engineer import (
    AutoGenReleaseEngineer,
    execute_shell,
    read_file,
    write_file,
    list_directory,
)
from agents.autogen.marketing_manager import (
    AutoGenMarketingManager,
    web_search,
    fetch_webpage,
    create_social_post,
    analyze_sentiment,
)
from agents.autogen.support_engineer import (
    AutoGenSupportEngineer,
    list_emails,
    send_email,
    list_calendar_events,
    create_calendar_event,
    get_sentry_issues,
    get_langfuse_traces,
    create_support_ticket,
)

# AutoGen imports
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
    from autogen_agentchat.teams import SelectorGroupChat
    from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
    from autogen_core.models import ModelFamily

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False
    AssistantAgent = None
    TaskResult = None
    SelectorGroupChat = None
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


TEAM_COORDINATOR_PROMPT = """You are the Team Coordinator for VibeTeam.

Your role is to:
1. Analyze incoming tasks and route them to the appropriate team member
2. Coordinate multi-agent tasks that require collaboration
3. Summarize results and next steps

## Team Members
- **ReleaseEngineer (Einstein)**: Deployments, CI/CD, infrastructure, Git operations
- **MarketingManager (Ada)**: Content creation, social media, web research, brand monitoring
- **SupportEngineer (Grace)**: Customer support, email, calendar, error tracking

## Routing Guidelines
- Deploy/release tasks -> ReleaseEngineer
- Content/social/marketing tasks -> MarketingManager
- Email/calendar/support tasks -> SupportEngineer
- Complex tasks -> Coordinate between agents

When a task is complete, respond with 'TASK_COMPLETE' to signal termination.
"""


class AutoGenTeam:
    """
    Team orchestration for AutoGen agents.

    Uses SelectorGroupChat to dynamically select the appropriate agent
    based on task content and conversation context.
    """

    def __init__(self, config: AgentConfig | None = None):
        if not AUTOGEN_AVAILABLE:
            raise ImportError(
                "AutoGen not installed. Run: pip install 'autogen-agentchat' 'autogen-ext[openai,azure]'"
            )

        self.config = config or AgentConfig()
        self.model_client = self._create_model_client()
        self._agents: dict[str, AssistantAgent] = {}
        self._team: SelectorGroupChat | None = None

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

    def _get_agents(self) -> list["AssistantAgent"]:
        """Create all team agents."""
        if not self._agents:
            # Release Engineer
            self._agents["release_engineer"] = AssistantAgent(
                name="ReleaseEngineer",
                model_client=self.model_client,
                tools=[execute_shell, read_file, write_file, list_directory],
                system_message="""You are Einstein, the Release Engineer.
                Handle deployments, CI/CD, infrastructure, and Git operations.
                When your part is done, let the coordinator know.""",
                description="Handles deployments, CI/CD pipelines, k3s cluster management, and infrastructure.",
            )

            # Marketing Manager
            self._agents["marketing_manager"] = AssistantAgent(
                name="MarketingManager",
                model_client=self.model_client,
                tools=[web_search, fetch_webpage, create_social_post, analyze_sentiment],
                system_message="""You are Ada, the Marketing Manager.
                Handle content creation, social media, web research, and brand monitoring.
                When your part is done, let the coordinator know.""",
                description="Handles content creation, social media posts, market research, and brand monitoring.",
            )

            # Support Engineer
            self._agents["support_engineer"] = AssistantAgent(
                name="SupportEngineer",
                model_client=self.model_client,
                tools=[
                    list_emails,
                    send_email,
                    list_calendar_events,
                    create_calendar_event,
                    get_sentry_issues,
                    get_langfuse_traces,
                    create_support_ticket,
                ],
                system_message="""You are Grace, the Support Engineer.
                Handle customer support, email, calendar, and error monitoring.
                When your part is done, let the coordinator know.""",
                description="Handles customer support, email, calendar, Sentry errors, and Langfuse traces.",
            )

        return list(self._agents.values())

    def _create_team(self) -> "SelectorGroupChat":
        """Create the SelectorGroupChat team."""
        if self._team is None:
            agents = self._get_agents()

            # Termination conditions
            termination = TextMentionTermination("TASK_COMPLETE") | MaxMessageTermination(20)

            self._team = SelectorGroupChat(
                participants=agents,
                model_client=self.model_client,
                termination_condition=termination,
                selector_prompt="""You are coordinating a team of agents. Based on the conversation,
select the next agent to speak:

Participants: {participants}

Agent roles:
{roles}

Conversation history:
{history}

Select the agent best suited to continue. If the task is complete, have the last speaker say 'TASK_COMPLETE'.
Reply with just the agent name.""",
            )

        return self._team

    def parse_mention(self, text: str) -> str | None:
        """
        Parse @mention from text to determine target agent.

        Supported mentions:
        - @ReleaseEngineer, @release, @einstein
        - @MarketingManager, @marketing, @ada
        - @SupportEngineer, @support, @grace
        """
        text_lower = text.lower()

        release_patterns = ["@releaseengineer", "@release", "@einstein"]
        marketing_patterns = ["@marketingmanager", "@marketing", "@ada"]
        support_patterns = ["@supportengineer", "@support", "@grace"]

        for pattern in release_patterns:
            if pattern in text_lower:
                return "release_engineer"

        for pattern in marketing_patterns:
            if pattern in text_lower:
                return "marketing_manager"

        for pattern in support_patterns:
            if pattern in text_lower:
                return "support_engineer"

        return None

    async def run_single_agent_async(
        self,
        task: str,
        role: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Run task with a specific agent."""
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        # Get the specific agent
        agents = self._get_agents()
        agent = self._agents.get(role)
        if not agent:
            return {"error": f"Unknown role: {role}"}

        session = get_or_create_session(
            framework="autogen",
            role=role,
            context_type=context_type,
            context_id=context_id,
        )

        # Run the agent
        result: TaskResult = await agent.run(task=task)

        # Extract response
        response = ""
        if result.messages:
            for msg in reversed(result.messages):
                if hasattr(msg, "content") and msg.content:
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
            "agent": role,
        }

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Route and execute task with appropriate agent(s).

        If task mentions a specific agent, route directly.
        Otherwise, use SelectorGroupChat for multi-agent coordination.

        Args:
            task: The task description (may contain @mentions)
            context_type: Type of context (issue, pr, slack, etc.)
            context_id: ID for the context

        Returns:
            dict with response, agent(s) used, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        # Check for @mention
        role = self.parse_mention(task)
        if role:
            return await self.run_single_agent_async(task, role, context_type, context_id)

        # Use team for multi-agent coordination
        session = get_or_create_session(
            framework="autogen",
            role="team",
            context_type=context_type,
            context_id=context_id,
        )

        team = self._create_team()
        result: TaskResult = await team.run(task=task)

        # Extract all agent responses
        responses = []
        agents_used = set()
        for msg in result.messages:
            if hasattr(msg, "source") and hasattr(msg, "content"):
                agent_name = str(msg.source)
                content = str(msg.content) if msg.content else ""
                if content:
                    responses.append(f"[{agent_name}]: {content}")
                    agents_used.add(agent_name)

        full_response = "\n\n".join(responses)

        # Update session
        session.add_message("user", task)
        session.add_message("assistant", full_response, agents=list(agents_used))
        get_session_store().save(session)

        return {
            "response": full_response,
            "session_key": session.key,
            "session_id": session.session_id,
            "framework": "autogen",
            "agents": list(agents_used),
            "message_count": len(result.messages),
        }

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Sync version of run_async."""
        return asyncio.run(self.run_async(task, context_type, context_id))

    async def close(self) -> None:
        """Close all agent connections."""
        if self.model_client:
            await self.model_client.close()


def create_team(config: AgentConfig | None = None) -> AutoGenTeam:
    """Factory function to create AutoGen team."""
    return AutoGenTeam(config)
